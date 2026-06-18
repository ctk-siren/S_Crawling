"""
세이렌 크롤링 대시보드 — Flask 웹 서버.

페이지
  GET  /                        공고 대시보드(1페이지)
  GET  /hotdeal                 핫딜(2페이지)

API (JSON)
  POST   /api/keywords                  공고 키워드 추가
  DELETE /api/keywords/<id>             공고 키워드 삭제
  POST   /api/hotdeal-keywords          핫딜 키워드 추가(+즉시 수집)
  DELETE /api/hotdeal-keywords/<id>     핫딜 키워드 삭제
  POST   /api/hotdeal-keywords/<id>/refresh  해당 키워드 재수집
  POST   /api/crawl                     공고 수동 수집(테스트용)

응답 규약: 성공 {"ok": true, ...}, 실패 {"ok": false, "error": "..."}
"""

import logging
import socket

from flask import Flask, jsonify, render_template, request

import config
import crawler
import database as db
from scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)


# ----------------------------------------------------------------------------
# 페이지
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    """공고 대시보드. 신규·매칭수 우선 정렬된 공고와 키워드 목록을 보여준다."""
    announcements = db.get_announcements()
    keywords = db.get_keywords()
    last_crawled = db.get_meta("last_crawled_at", "아직 수집 안 함")
    return render_template(
        "index.html",
        announcements=announcements,
        keywords=keywords,
        last_crawled=last_crawled,
        total=len(announcements),
    )


@app.route("/hotdeal")
def hotdeal():
    """핫딜 페이지. 등록된 키워드별 수집 결과를 보여준다."""
    keywords = db.get_hotdeal_keywords()
    data = []
    for kw in keywords:
        data.append(
            {
                "id": kw["id"],
                "keyword": kw["keyword"],
                "deals": db.get_hotdeals_by_keyword(kw["keyword"]),
            }
        )
    return render_template("hotdeal.html", groups=data, site_name=config.HOTDEAL_SITE_NAME)


# ----------------------------------------------------------------------------
# 공고 키워드 API
# ----------------------------------------------------------------------------
@app.route("/api/keywords", methods=["POST"])
def api_add_keyword():
    payload = request.get_json(silent=True) or {}
    keyword = (payload.get("keyword") or "").strip()
    category = payload.get("category", "extended")
    if not keyword:
        return jsonify({"ok": False, "error": "키워드를 입력하세요"}), 400
    try:
        added, row = db.add_keyword(keyword, category)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "added": added, "keyword": row})


@app.route("/api/keywords/<int:keyword_id>", methods=["DELETE"])
def api_delete_keyword(keyword_id):
    deleted = db.delete_keyword(keyword_id)
    if not deleted:
        return jsonify({"ok": False, "error": "해당 키워드가 없습니다"}), 404
    return jsonify({"ok": True})


# ----------------------------------------------------------------------------
# 핫딜 키워드 API
# ----------------------------------------------------------------------------
@app.route("/api/hotdeal-keywords", methods=["POST"])
def api_add_hotdeal_keyword():
    payload = request.get_json(silent=True) or {}
    keyword = (payload.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "키워드를 입력하세요"}), 400
    try:
        added, row = db.add_hotdeal_keyword(keyword)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    # 등록 즉시 수집 (소스 전체 합산, 실패해도 키워드는 남는다)
    deals = crawler.crawl_hotdeal(keyword)
    db.replace_hotdeals(keyword, deals)

    return jsonify(
        {
            "ok": True,
            "added": added,
            "keyword": row,
            "deals": db.get_hotdeals_by_keyword(keyword),
        }
    )


@app.route("/api/hotdeal-keywords/<int:keyword_id>", methods=["DELETE"])
def api_delete_hotdeal_keyword(keyword_id):
    deleted = db.delete_hotdeal_keyword(keyword_id)
    if not deleted:
        return jsonify({"ok": False, "error": "해당 키워드가 없습니다"}), 404
    return jsonify({"ok": True})


@app.route("/api/hotdeal-keywords/<int:keyword_id>/refresh", methods=["POST"])
def api_refresh_hotdeal(keyword_id):
    keywords = {k["id"]: k["keyword"] for k in db.get_hotdeal_keywords()}
    keyword = keywords.get(keyword_id)
    if not keyword:
        return jsonify({"ok": False, "error": "해당 키워드가 없습니다"}), 404
    deals = crawler.crawl_hotdeal(keyword)
    db.replace_hotdeals(keyword, deals)
    return jsonify({"ok": True, "deals": db.get_hotdeals_by_keyword(keyword)})


# ----------------------------------------------------------------------------
# 공고 수동 수집 (테스트/즉시 갱신용)
# ----------------------------------------------------------------------------
@app.route("/api/crawl", methods=["POST"])
def api_crawl():
    summary = crawler.run_crawl()
    return jsonify({"ok": True, "summary": summary})


# ----------------------------------------------------------------------------
# 기동
# ----------------------------------------------------------------------------
def bootstrap():
    """DB 초기화 + 스케줄러 기동. import 시점·직접 실행 모두에서 1회만 동작."""
    db.init_db()
    start_scheduler()


def _is_port_free(host, port):
    """
    host:port 에 listen 중인 서버가 있는지 연결을 시도해 확인한다.
    연결되면(누가 듣고 있으면) 사용 중, 연결 거부면 비어 있음.
    (Windows 의 SO_REUSEADDR 는 중복 바인딩을 허용해 bind 검사가 부정확하므로 connect 로 확인)
    """
    check_host = "127.0.0.1" if host in ("0.0.0.0", "", None) else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((check_host, port)) != 0


def find_available_port(host, preferred):
    """
    preferred 포트가 비어 있으면 그대로, 아니면 그 다음 빈 포트를 찾아 반환한다.
    preferred 부터 +50 까지 훑고, 그래도 없으면 OS 가 임의 빈 포트를 배정(port 0).
    """
    for port in range(preferred, preferred + 50):
        if _is_port_free(host, port):
            return port
    # 마지막 수단 — OS 가 비어 있는 포트를 임의로 골라준다
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    bootstrap()

    port = find_available_port(config.WEB_HOST, config.WEB_PORT)
    if port != config.WEB_PORT:
        logging.warning(
            "포트 %s 가 사용 중이라 %s 포트로 대신 엽니다.", config.WEB_PORT, port
        )
    logging.info("웹 서버 시작 — http://127.0.0.1:%s (종료: Ctrl+C)", port)

    # use_reloader=False — 리로더가 프로세스를 두 번 띄워 스케줄러가 중복 기동되는 것을 막는다.
    app.run(host=config.WEB_HOST, port=port, debug=True, use_reloader=False)
