"""
공고·핫딜 크롤러.

설계
  - 사이트별 crawl_xxx() 함수는 같은 시그니처(인자 없음 → dict 리스트)를 가진다.
  - 각 dict 키: source, title, url, body, deadline, fund_scale
  - run_crawl() 이 전체 사이트를 돌며 수집 → 키워드 매칭 → 매칭된 것만 DB 저장.
  - 한 사이트가 실패해도 전체 수집은 계속된다(외과적 격리, SA-STD-001 원칙 3).

수집 정책
  - NTIS·SMTECH·K-Startup 은 HTML 파싱(라이브 검증 완료).
  - g2b·iris 는 SPA 라 스크래핑 불가 → 공공데이터포털 Open API 사용(서비스키 필요).
  - 목록에는 본문·지원규모가 없어 제목 기준으로 키워드 매칭한다.
    (상세 페이지 보강은 추후 별도 단계)
"""

import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

import config
import database as db


# ----------------------------------------------------------------------------
# 공통 유틸
# ----------------------------------------------------------------------------
def fetch(url, params=None, timeout=None):
    """GET 요청. 실패 시 예외를 올려 호출부에서 사이트 단위로 격리 처리한다."""
    resp = requests.get(
        url,
        params=params,
        headers=config.REQUEST_HEADERS,
        timeout=timeout or config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp


def match_keywords(text, keywords):
    """text 안에 등장하는 키워드 목록을 반환 (대소문자 무시, 중복 제거, 순서 유지)."""
    if not text:
        return []
    low = text.lower()
    matched = []
    for kw in keywords:
        if kw and kw.lower() in low and kw not in matched:
            matched.append(kw)
    return matched


def _clean(text):
    """공백 정리."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def _site_name(key):
    for s in config.SITES:
        if s["key"] == key:
            return s["name"]
    return key


def _ntis_title(raw):
    """
    NTIS 제목은 '공고명_(연도)사업명' 형식으로 둘을 이어붙여 온다.
    둘이 같으면 하나로 합치고, 다르면 ' / ' 로 구분해 보여준다.
    """
    parts = [p.strip() for p in re.split(r"_\(\d{4}\)", raw) if p.strip()]
    out = []
    for p in parts:
        if p not in out:
            out.append(p)
    return " / ".join(out) if out else raw.strip()


# ----------------------------------------------------------------------------
# NTIS — 실제 구현 (라이브 검증 완료)
#   목록 페이지: table.basic_list 의 tbody tr
#   컬럼: [0]체크박스 [1]번호 [2]상태 [3]제목(상세링크) [4]부처명 [5]공고일 [6]마감일 [7]D-day
# ----------------------------------------------------------------------------
NTIS_LIST_URL = "https://www.ntis.go.kr/rndgate/eg/un/ra/mng.do"
NTIS_BASE = "https://www.ntis.go.kr"


def _ntis_detail(url):
    """
    NTIS 상세 페이지(div.notice_area)에서 공고금액(지원규모)과 공고내용(본문)을 추출.
    실패하면 ('', '') 를 돌려준다(상세 보강은 best-effort).
    """
    try:
        resp = fetch(url)
    except Exception:
        return "", ""
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    area = soup.select_one("div.notice_area")
    if not area:
        return "", ""
    text = area.get_text(" ", strip=True)

    # 공고금액 : 117.32 억원  (금액에 소수점이 올 수 있고 단위가 억원/만원/원 등)
    fund = ""
    m = re.search(r"공고금액\s*:?\s*([\d,.]+)\s*(억원|만원|원)?", text)
    if m and m.group(1).strip(".0,") != "":
        fund = f"{m.group(1)}{m.group(2) or ''}"

    # 공고내용 라벨 이후가 본문. 너무 길면 매칭·저장 부담을 줄이려 앞부분만.
    body = ""
    idx = text.find("공고내용")
    if idx >= 0:
        body = text[idx + len("공고내용"):].strip()[:2000]
    return fund, body


def crawl_ntis():
    items = []
    resp = fetch(NTIS_LIST_URL)
    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.select_one("table.basic_list")
    if not table:
        return items

    name = _site_name("ntis")
    for tr in table.select("tbody tr")[: config.MAX_ITEMS_PER_SITE]:
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue

        link = tds[3].find("a", href=True)
        title = _ntis_title(_clean(link.get_text() if link else tds[3].get_text()))
        if not title:
            continue

        href = link["href"] if link else ""
        if href.startswith("/"):
            href = NTIS_BASE + href

        ministry = _clean(tds[4].get_text())   # 부처명
        deadline = _clean(tds[6].get_text())    # 마감일

        # 기본 본문은 제목+부처명. 상세 보강이 켜져 있으면 공고내용·공고금액을 더한다.
        body = f"{title} {ministry}"
        fund_scale = ""
        if config.NTIS_FETCH_DETAIL and href.startswith("http"):
            d_fund, d_body = _ntis_detail(href)
            if d_fund:
                fund_scale = d_fund
            if d_body:
                body = f"{body} {d_body}"
            time.sleep(config.DETAIL_REQUEST_DELAY)  # 서버 예의

        items.append(
            {
                "source": name,
                "title": title,
                "url": href,
                "body": body,
                "deadline": deadline,
                "fund_scale": fund_scale,
            }
        )
    return items


# ----------------------------------------------------------------------------
# SMTECH — 실제 구현 (라이브 검증 완료)
#   목록: caption '사업공고 목록' 테이블의 tbody tr
#   컬럼: [0]번호 [1]분류 [2]사업명 [3]공고명(상세링크) [4]접수기간 [5]공고일자 [6]-
# ----------------------------------------------------------------------------
SMTECH_LIST_URL = "https://www.smtech.go.kr/front/ifg/no/notice02_list.do"
SMTECH_BASE = "https://www.smtech.go.kr"


def crawl_smtech():
    items = []
    resp = fetch(SMTECH_LIST_URL)
    soup = BeautifulSoup(resp.text, "lxml")

    # caption 으로 사업공고 목록 테이블을 찾는다(로그인 폼 등 다른 표 제외)
    table = None
    for t in soup.select("table"):
        cap = t.find("caption")
        if cap and "사업공고" in cap.get_text():
            table = t
            break
    if table is None:
        return items

    name = _site_name("smtech")
    for tr in table.select("tbody tr")[: config.MAX_ITEMS_PER_SITE]:
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue

        title = _clean(tds[3].get_text())
        if not title:
            continue

        # SMTECH 자체 공고만 상세 딥링크가 있고, IRIS 위탁 공고는 goMove()(IRIS 홈으로
        # 리다이렉트)라 딥링크가 없다. 딥링크가 없으면 목록 페이지로 폴백한다.
        link = tr.select_one('a[href*="notice02_detail"]')
        if link:
            href = re.sub(r";jsessionid=[^?]*", "", link["href"])  # 세션ID 제거
            if href.startswith("/"):
                href = SMTECH_BASE + href
        else:
            href = SMTECH_LIST_URL

        biz = _clean(tds[2].get_text())          # 사업명
        period = tds[4].get_text()                # 접수기간 'YYYY. MM. DD ~ YYYY. MM. DD'
        deadline = re.sub(r"\s", "", period.split("~")[-1]) if "~" in period else _clean(period)

        items.append(
            {
                "source": name,
                "title": title,
                "url": href,
                "body": f"{title} {biz}",  # 사업명까지 매칭 대상에 포함
                "deadline": deadline,
                "fund_scale": "",
            }
        )
    return items


# ----------------------------------------------------------------------------
# K-Startup — 실제 구현 (라이브 검증 완료)
#   목록(모집중): li.notice
#   제목 p.tit, 링크 go_view(pbancSn), 마감 .bottom '마감일자 YYYY-MM-DD'
#   상세 URL: ...bizpbanc-ongoing.do?schM=view&pbancSn=<sn>
# ----------------------------------------------------------------------------
KSTARTUP_LIST_URL = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"


def crawl_kstartup():
    items = []
    resp = fetch(KSTARTUP_LIST_URL)
    soup = BeautifulSoup(resp.text, "lxml")

    name = _site_name("kstartup")
    for li in soup.select("li.notice")[: config.MAX_ITEMS_PER_SITE]:
        tit = li.select_one("p.tit")
        title = _clean(tit.get_text()) if tit else ""
        if not title:
            continue

        a = li.select_one("a[href*=go_view]")
        sn = None
        if a:
            m = re.search(r"go_view\((\d+)\)", a.get("href", ""))
            if m:
                sn = m.group(1)
        url = f"{KSTARTUP_LIST_URL}?schM=view&pbancSn={sn}" if sn else KSTARTUP_LIST_URL

        deadline = ""
        bottom = li.select_one(".bottom")
        if bottom:
            m = re.search(r"마감일자\s*([\d.\-]+)", bottom.get_text(" ", strip=True))
            if m:
                deadline = m.group(1)

        items.append(
            {
                "source": name,
                "title": title,
                "url": url,
                "body": title,
                "deadline": deadline,
                "fund_scale": "",
            }
        )
    return items


# ----------------------------------------------------------------------------
# g2b / iris — 공공데이터포털 Open API (SPA 라 스크래핑 불가)
#   서비스키(config.DATA_GO_KR_SERVICE_KEY)가 없으면 빈 리스트.
#   ※ 응답 필드명은 공식 문서 기준으로 작성. 키 발급 후 실제 응답으로 검증·조정 필요.
# ----------------------------------------------------------------------------

# 조달청 나라장터 입찰공고정보서비스 — 용역(service) 목록
# 차세대 나라장터(/ad/) 경로. 구버전(/BidPublicInfoService/)은 500 을 반환해 폐기로 판단.
G2B_ENDPOINT = "http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc"

# 과학기술정보통신부 사업공고 (R&D 공고 피드, IRIS 대체)
MSIT_ENDPOINT = "http://apis.data.go.kr/1721000/msitannouncementinfo/businessAnnouncMentList"


def _as_item_list(body):
    """data.go.kr 응답의 items 가 list/dict/단일 어느 형태든 list 로 정규화."""
    items = body.get("items") if isinstance(body, dict) else None
    if items is None:
        return []
    if isinstance(items, dict):
        # {"item": [...]} 또는 {"item": {...}} 형태
        inner = items.get("item", [])
        return inner if isinstance(inner, list) else [inner]
    if isinstance(items, list):
        return items
    return []


def crawl_g2b():
    """나라장터 입찰공고(용역) 최근 N일치를 Open API 로 수집."""
    key = config.DATA_GO_KR_SERVICE_KEY
    if not key:
        return []

    end = datetime.now()
    begin = end - timedelta(days=config.G2B_LOOKBACK_DAYS)
    params = {
        "serviceKey": key,
        "pageNo": 1,
        "numOfRows": config.MAX_ITEMS_PER_SITE,
        "inqryDiv": 1,  # 1 = 공고게시일시 기준 조회
        "inqryBgnDt": begin.strftime("%Y%m%d%H%M"),
        "inqryEndDt": end.strftime("%Y%m%d%H%M"),
        "type": "json",
    }
    resp = fetch(G2B_ENDPOINT, params=params, timeout=config.DATA_GO_KR_TIMEOUT)
    body = resp.json().get("response", {}).get("body", {})

    name = _site_name("g2b")
    items = []
    for it in _as_item_list(body):
        title = _clean(it.get("bidNtceNm", ""))
        if not title:
            continue
        inst = _clean(it.get("ntceInsttNm", ""))       # 공고기관명
        deadline = _clean(it.get("bidClseDt", ""))      # 입찰마감일시
        url = it.get("bidNtceDtlUrl", "") or it.get("bidNtceUrl", "")
        budget = it.get("asignBdgtAmt") or it.get("presmptPrce") or ""  # 배정예산 우선
        items.append(
            {
                "source": name,
                "title": title,
                "url": url,
                "body": f"{title} {inst}",
                "deadline": deadline,
                "fund_scale": _price_digits(str(budget)) if budget else "",
            }
        )
    return items


def _msit_items(payload):
    """MSIT 응답은 response=[{header},{body}] 리스트, items 각 원소가 {'item':{...}}."""
    resp = payload.get("response")
    raw = []
    if isinstance(resp, list):
        for part in resp:
            if isinstance(part, dict) and "body" in part:
                items = (part["body"] or {}).get("items", [])
                raw = items if isinstance(items, list) else [items]
                break
    elif isinstance(resp, dict):
        raw = _as_item_list(resp.get("body", {}))
    # {'item': {...}} 래핑 풀기
    return [(r.get("item", r) if isinstance(r, dict) else r) for r in raw]


def crawl_iris():
    """R&D 사업공고(과기부 사업공고 API)를 수집. IRIS 계열 R&D 공고 피드."""
    key = config.DATA_GO_KR_SERVICE_KEY
    if not key:
        return []

    params = {
        "ServiceKey": key,
        "pageNo": 1,
        "numOfRows": config.MAX_ITEMS_PER_SITE,
        "returnType": "json",
    }
    resp = fetch(MSIT_ENDPOINT, params=params, timeout=config.DATA_GO_KR_TIMEOUT)

    name = _site_name("iris")
    items = []
    for it in _msit_items(resp.json()):
        if not isinstance(it, dict):
            continue
        title = _clean(it.get("subject", "") or it.get("title", ""))
        if not title:
            continue
        items.append(
            {
                "source": name,
                "title": title,
                "url": it.get("viewUrl", "") or it.get("url", ""),
                "body": f"{title} {_clean(it.get('deptName', ''))}",
                "deadline": "",  # MSIT 사업공고 응답에 마감일 필드 없음(게시일 pressDt만 제공)
                "fund_scale": "",
            }
        )
    return items


# 사이트 key → 크롤러 함수 매핑
CRAWLERS = {
    "ntis": crawl_ntis,
    "g2b": crawl_g2b,
    "smtech": crawl_smtech,
    "iris": crawl_iris,
    "kstartup": crawl_kstartup,
}


# ----------------------------------------------------------------------------
# 전체 수집 파이프라인
# ----------------------------------------------------------------------------
def run_crawl():
    """
    전체 사이트 수집 → 키워드 매칭 → 매칭된 공고만 DB 저장.
    반환: 사이트별/합계 수집 요약 dict.
    """
    db.init_db()
    keywords = db.get_keyword_strings()

    summary = {"sites": {}, "fetched": 0, "matched": 0, "saved": 0, "errors": {}}

    for site in config.SITES:
        key = site["key"]
        crawler = CRAWLERS.get(key)
        if crawler is None:
            continue

        try:
            raw_items = crawler()
        except Exception as e:  # 사이트 단위 격리 — 하나 실패해도 나머지 진행
            summary["errors"][key] = f"{type(e).__name__}: {e}"
            summary["sites"][key] = {"fetched": 0, "matched": 0, "saved": 0}
            continue

        s_fetched = len(raw_items)
        s_matched = 0
        s_saved = 0

        for item in raw_items:
            text = f"{item.get('title', '')} {item.get('body', '')}"
            matched = match_keywords(text, keywords)
            if not matched:
                continue
            s_matched += 1
            item["matched_keywords"] = matched
            if db.save_announcement(item):
                s_saved += 1

        summary["sites"][key] = {
            "fetched": s_fetched,
            "matched": s_matched,
            "saved": s_saved,
        }
        summary["fetched"] += s_fetched
        summary["matched"] += s_matched
        summary["saved"] += s_saved

    # 오늘 수집분 강조 플래그 갱신 + 마지막 수집 시각 기록
    db.refresh_is_new_flags()
    db.set_meta("last_crawled_at", db._now())

    return summary


# ----------------------------------------------------------------------------
# 핫딜 — 여러 가격 소스 통합
#   다나와·에누리는 라이브 검증 완료(키 불필요).
#   네이버 쇼핑은 봇 차단(HTTP 418)으로 requests 스크래핑 불가 → 빈 리스트.
#     (네이버 가격이 필요하면 무료 Open API client id/secret 발급 후 별도 구현)
#   각 소스는 try/except 로 격리 — 한 곳이 막혀도 나머지 소스는 수집된다.
# ----------------------------------------------------------------------------
DANAWA_SEARCH = "https://search.danawa.com/dsearch.php"
ENURI_SEARCH = "http://www.enuri.com/search.jsp"
NAVER_SHOP_SEARCH = "https://search.shopping.naver.com/search/all"


def _price_digits(text):
    """가격 문자열에서 '12,345원' 형태로 정리. 숫자가 없으면 원문 유지."""
    digits = re.sub(r"[^\d]", "", text or "")
    if not digits:
        return _clean(text)
    return f"{int(digits):,}원"


def _hotdeal_danawa(keyword):
    items = []
    resp = fetch(DANAWA_SEARCH, params={"query": keyword})
    soup = BeautifulSoup(resp.text, "lxml")
    for li in soup.select("li.prod_item"):
        if "prod_ad_item" in (li.get("class") or []):
            continue  # 광고 제외
        name_el = li.select_one("p.prod_name a")
        price_el = li.select_one("p.price_sect strong")
        if not name_el:
            continue
        name = _clean(name_el.get_text())
        if not name:
            continue
        items.append(
            {
                "product_name": name,
                "price": _price_digits(price_el.get_text() if price_el else ""),
                "url": name_el.get("href", ""),
                "site": "다나와",
            }
        )
        if len(items) >= config.HOTDEAL_MAX_ITEMS:
            break
    return items


def _hotdeal_enuri(keyword):
    items = []
    resp = fetch(ENURI_SEARCH, params={"keyword": keyword})
    soup = BeautifulSoup(resp.text, "lxml")
    for li in soup.select("li.product-item"):
        name_el = li.select_one("h3.product-name")
        price_el = li.select_one("span.price-low")
        link_el = li.select_one("a.product-link")
        if not name_el:
            continue
        name = _clean(name_el.get_text())
        if not name:
            continue
        items.append(
            {
                "product_name": name,
                "price": _price_digits(price_el.get_text() if price_el else ""),
                "url": link_el.get("href", "") if link_el else "",
                "site": "에누리",
            }
        )
        if len(items) >= config.HOTDEAL_MAX_ITEMS:
            break
    return items


def _hotdeal_naver(keyword):
    """네이버 쇼핑은 봇 차단(418)으로 현재 수집 불가. 빈 리스트 반환."""
    return []


# 핫딜 소스 함수 목록 (순서대로 시도, 결과 합산)
HOTDEAL_SOURCES = [_hotdeal_danawa, _hotdeal_enuri, _hotdeal_naver]


def crawl_hotdeal(keyword):
    """
    여러 가격 소스에서 키워드 검색 결과(상품명·가격·링크·소스)를 합쳐 반환한다.
    소스별로 격리해 한 곳이 막혀도 나머지는 수집한다.
    반환: dict 리스트 {product_name, price, url, site}
    """
    results = []
    for source in HOTDEAL_SOURCES:
        try:
            results.extend(source(keyword))
        except Exception:
            continue  # 해당 소스만 건너뛴다
    return results


if __name__ == "__main__":
    # 단독 실행 — NTIS 수집 및 매칭 동작 확인
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    db.init_db()
    ntis = crawl_ntis()
    print(f"NTIS 수집 건수: {len(ntis)}")
    if ntis:
        print("첫 공고 예시:", ntis[0])

    result = run_crawl()
    print("수집 요약:", result)
