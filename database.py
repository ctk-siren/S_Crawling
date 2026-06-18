"""
SQLite 데이터 계층.

테이블
  announcements      수집된 공고 (키워드 매칭된 것만 저장)
  keywords           공고 필터링용 키워드 (core/extended)
  hotdeal_keywords   핫딜 검색 키워드
  hotdeals           핫딜 검색 결과 (가격/링크)
  meta               key-value 메타 (last_crawled_at 등)

설계 메모
  - announcements.url 을 UNIQUE 로 두어 중복 수집을 자동 방지한다.
  - matched_keywords 는 콤마로 이어붙인 문자열로 저장한다.
  - is_new 는 "오늘 수집된 신규 공고" 강조 표시용 플래그.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

import config


# ----------------------------------------------------------------------------
# 연결 헬퍼
# ----------------------------------------------------------------------------
@contextmanager
def get_conn():
    """row_factory 가 설정된 연결을 with 블록으로 제공한다."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now():
    """ISO 형식 현재 시각 문자열."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return datetime.now().strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------
# 초기화
# ----------------------------------------------------------------------------
def init_db():
    """테이블을 생성하고, 키워드 테이블이 비어 있으면 초기 키워드를 시드한다."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS announcements (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                source           TEXT    NOT NULL,
                title            TEXT    NOT NULL,
                url              TEXT    NOT NULL UNIQUE,
                body             TEXT,
                deadline         TEXT,
                fund_scale       TEXT,
                matched_keywords TEXT,
                collected_at     TEXT    NOT NULL,
                is_new           INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS keywords (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword    TEXT    NOT NULL UNIQUE,
                category   TEXT    NOT NULL DEFAULT 'extended',
                created_at TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS hotdeal_keywords (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword    TEXT    NOT NULL UNIQUE,
                created_at TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS hotdeals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword      TEXT    NOT NULL,
                product_name TEXT    NOT NULL,
                price        TEXT,
                url          TEXT,
                site         TEXT,
                collected_at TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )

        # 키워드 시드 (최초 1회)
        cur.execute("SELECT COUNT(*) AS c FROM keywords")
        if cur.fetchone()["c"] == 0:
            now = _now()
            cur.executemany(
                "INSERT INTO keywords (keyword, category, created_at) VALUES (?, ?, ?)",
                [(kw, cat, now) for kw, cat in config.INITIAL_KEYWORDS],
            )


# ----------------------------------------------------------------------------
# 키워드 (공고 필터링용)
# ----------------------------------------------------------------------------
def get_keywords():
    """키워드 목록을 dict 리스트로 반환 (core 먼저)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, keyword, category, created_at FROM keywords "
            "ORDER BY CASE category WHEN 'core' THEN 0 ELSE 1 END, id"
        ).fetchall()
        return [dict(r) for r in rows]


def get_keyword_strings():
    """매칭에 쓰기 위한 키워드 문자열 리스트."""
    with get_conn() as conn:
        rows = conn.execute("SELECT keyword FROM keywords").fetchall()
        return [r["keyword"] for r in rows]


def add_keyword(keyword, category="extended"):
    """키워드 추가. 중복이면 무시. 추가/기존 여부와 행을 반환."""
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("빈 키워드는 추가할 수 없다")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO keywords (keyword, category, created_at) "
            "VALUES (?, ?, ?)",
            (keyword, category, _now()),
        )
        added = cur.rowcount > 0
        row = conn.execute(
            "SELECT id, keyword, category, created_at FROM keywords WHERE keyword = ?",
            (keyword,),
        ).fetchone()
        return added, dict(row)


def delete_keyword(keyword_id):
    """키워드 삭제. 삭제된 행 수 반환."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM keywords WHERE id = ?", (keyword_id,))
        return cur.rowcount


# ----------------------------------------------------------------------------
# 공고
# ----------------------------------------------------------------------------
def save_announcement(item):
    """
    공고 1건 저장. url 중복이면 무시(이미 수집된 공고).
    item dict 키: source, title, url, body, deadline, fund_scale, matched_keywords(list)
    저장 성공(신규) 시 True, 중복이면 False 반환.
    """
    matched = item.get("matched_keywords") or []
    matched_str = ",".join(matched)
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO announcements
                (source, title, url, body, deadline, fund_scale,
                 matched_keywords, collected_at, is_new)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                item.get("source", ""),
                item.get("title", ""),
                item.get("url", ""),
                item.get("body", ""),
                item.get("deadline", ""),
                item.get("fund_scale", ""),
                matched_str,
                _now(),
            ),
        )
        return cur.rowcount > 0


def get_announcements():
    """
    공고 목록 반환. 신규(오늘) 우선, 매칭 키워드 수 내림차순, 최신순.
    matched_keywords 는 리스트로 변환해 돌려준다.
    """
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM announcements").fetchall()

    items = []
    for r in rows:
        d = dict(r)
        kws = [k for k in (d.get("matched_keywords") or "").split(",") if k]
        d["matched_keywords"] = kws
        d["match_count"] = len(kws)
        items.append(d)

    items.sort(
        key=lambda x: (x["is_new"], x["match_count"], x["collected_at"]),
        reverse=True,
    )
    return items


def refresh_is_new_flags():
    """오늘 수집분만 is_new=1, 나머지는 0 으로 갱신."""
    today = _today()
    with get_conn() as conn:
        conn.execute(
            "UPDATE announcements SET is_new = "
            "CASE WHEN substr(collected_at, 1, 10) = ? THEN 1 ELSE 0 END",
            (today,),
        )


# ----------------------------------------------------------------------------
# 핫딜 키워드
# ----------------------------------------------------------------------------
def get_hotdeal_keywords():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, keyword, created_at FROM hotdeal_keywords ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def add_hotdeal_keyword(keyword):
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("빈 키워드는 추가할 수 없다")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO hotdeal_keywords (keyword, created_at) VALUES (?, ?)",
            (keyword, _now()),
        )
        added = cur.rowcount > 0
        row = conn.execute(
            "SELECT id, keyword, created_at FROM hotdeal_keywords WHERE keyword = ?",
            (keyword,),
        ).fetchone()
        return added, dict(row)


def delete_hotdeal_keyword(keyword_id):
    """핫딜 키워드 삭제. 연관 핫딜 결과도 함께 정리."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT keyword FROM hotdeal_keywords WHERE id = ?", (keyword_id,)
        ).fetchone()
        cur = conn.execute("DELETE FROM hotdeal_keywords WHERE id = ?", (keyword_id,))
        if row:
            conn.execute("DELETE FROM hotdeals WHERE keyword = ?", (row["keyword"],))
        return cur.rowcount


# ----------------------------------------------------------------------------
# 핫딜 결과
# ----------------------------------------------------------------------------
def replace_hotdeals(keyword, items):
    """해당 키워드의 기존 핫딜 결과를 지우고 새 결과로 교체."""
    now = _now()
    with get_conn() as conn:
        conn.execute("DELETE FROM hotdeals WHERE keyword = ?", (keyword,))
        conn.executemany(
            """
            INSERT INTO hotdeals
                (keyword, product_name, price, url, site, collected_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    keyword,
                    it.get("product_name", ""),
                    it.get("price", ""),
                    it.get("url", ""),
                    it.get("site", config.HOTDEAL_SITE_NAME),
                    now,
                )
                for it in items
            ],
        )


def get_hotdeals_by_keyword(keyword):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM hotdeals WHERE keyword = ? ORDER BY id", (keyword,)
        ).fetchall()
        return [dict(r) for r in rows]


# ----------------------------------------------------------------------------
# 메타 (last_crawled_at 등)
# ----------------------------------------------------------------------------
def set_meta(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_meta(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


if __name__ == "__main__":
    # 단독 실행 시 DB 초기화 및 시드 확인
    init_db()
    print("DB 초기화 완료:", config.DB_PATH)
    print("등록 키워드:", get_keyword_strings())
