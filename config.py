"""
세이렌 크롤링 대시보드 설정값.

키워드는 최초 실행 시 DB에 시드로 삽입되고, 이후에는 UI/DB에서 관리한다.
이 파일은 초기값과 정적 설정(경로, 스케줄, 사이트, 요청 헤더)만 담는다.
"""

import os

# ----------------------------------------------------------------------------
# 경로 (Windows 로컬·Oracle Linux 양쪽 호환되도록 절대경로 계산)
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "siren.db")

# ----------------------------------------------------------------------------
# 웹 서버
#   WEB_PORT 가 이미 사용 중이면 app.py 가 자동으로 빈 포트를 찾아 연다.
# ----------------------------------------------------------------------------
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000

# ----------------------------------------------------------------------------
# 자동 수집 스케줄 (매일 오전 8시)
# ----------------------------------------------------------------------------
SCHEDULE_HOUR = 8
SCHEDULE_MINUTE = 0

# ----------------------------------------------------------------------------
# 초기 등록 키워드 (category: core | extended)
#   - core     핵심 키워드
#   - extended 확장 키워드
# 최초 DB 초기화 시에만 시드로 삽입된다. 이후 추가/삭제는 UI에서.
# ----------------------------------------------------------------------------
INITIAL_KEYWORDS = [
    # 핵심 키워드
    ("능동소음제어", "core"),
    ("층간소음", "core"),
    ("진동저감", "core"),
    ("AVC", "core"),
    ("주거환경개선", "core"),
    # 확장 키워드
    ("소음저감", "extended"),
    ("방음", "extended"),
    ("진동", "extended"),
    ("주거환경", "extended"),
    ("공동주택", "extended"),
    ("스마트홈", "extended"),
    ("IoT센서", "extended"),
    ("소음모니터링", "extended"),
]

# ----------------------------------------------------------------------------
# 공고 수집 대상 사이트
#   key       내부 식별자(크롤러 함수 매핑)
#   name      카드에 표시될 출처 이름
#   base_url  원문 베이스 URL
# ----------------------------------------------------------------------------
SITES = [
    {"key": "ntis", "name": "NTIS", "base_url": "https://www.ntis.go.kr"},
    {"key": "g2b", "name": "나라장터", "base_url": "https://www.g2b.go.kr"},
    {"key": "smtech", "name": "SMTECH", "base_url": "https://www.smtech.go.kr"},
    {"key": "iris", "name": "IRIS", "base_url": "https://www.iris.go.kr"},
    {"key": "kstartup", "name": "K-Startup", "base_url": "https://www.k-startup.go.kr"},
]

# ----------------------------------------------------------------------------
# HTTP 요청 설정
# ----------------------------------------------------------------------------
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}
REQUEST_TIMEOUT = 15  # 초

# 한 사이트에서 한 번에 가져올 최대 공고 수 (서버 부하·차단 방지)
MAX_ITEMS_PER_SITE = 30

# ----------------------------------------------------------------------------
# 공공데이터포털(data.go.kr) Open API 서비스키
#   g2b(나라장터)·iris(R&D 사업공고)는 SPA 라 스크래핑 불가 → 무료 Open API 사용.
#   키는 소스코드에 박지 않는다. 다음 순서로 읽으며, 둘 다 없으면 빈 값(해당 크롤러는 빈 리스트).
#     1) 환경변수 DATA_GO_KR_SERVICE_KEY
#     2) 같은 폴더의 service_key.txt 파일 내용 (.gitignore 로 깃 제외됨)
#   ※ 공공데이터포털의 '디코딩(Decoding) 일반 인증키'를 넣는다(requests 가 인코딩 처리).
# ----------------------------------------------------------------------------
def _load_service_key():
    from urllib.parse import unquote

    key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not key:
        key_file = os.path.join(BASE_DIR, "service_key.txt")
        if os.path.exists(key_file):
            with open(key_file, encoding="utf-8") as f:
                key = f.read().strip()
    if not key:
        return ""
    # 인코딩 키(%2B 등)든 디코딩 키(+ / =)든 디코딩 형태로 통일한다.
    # 그래야 requests 가 정확히 한 번만 URL 인코딩한다(이중 인코딩 방지).
    return unquote(key)


DATA_GO_KR_SERVICE_KEY = _load_service_key()

# data.go.kr API 는 가끔 응답이 느려 기본 타임아웃(15초)으로는 ReadTimeout 이 난다. 더 길게 준다.
DATA_GO_KR_TIMEOUT = 30

# g2b 입찰공고 조회 기간(최근 N일)
G2B_LOOKBACK_DAYS = 3

# NTIS 상세 페이지를 추가로 받아 공고금액(지원규모)·본문을 보강할지 여부.
#   True 면 목록 건수만큼(보통 ~10건) 상세 요청을 더 한다(본문 키워드 매칭 가능).
NTIS_FETCH_DETAIL = True
# 상세 요청 사이 지연(초) — 서버 예의
DETAIL_REQUEST_DELAY = 0.3

# ----------------------------------------------------------------------------
# 핫딜 수집 설정 (네이버 쇼핑 검색 기본)
# ----------------------------------------------------------------------------
HOTDEAL_SITE_NAME = "네이버쇼핑"
HOTDEAL_MAX_ITEMS = 10  # 키워드당 표시할 최대 상품 수

# ----------------------------------------------------------------------------
# AI 관련도 판단 (Claude API)
#   공고가 회사 비전과 관련 있는지 Claude 가 판단하고 한 줄 이유를 붙인다.
#   키는 소스에 박지 않는다. 환경변수 ANTHROPIC_API_KEY → anthropic_key.txt 파일 순.
#   키가 없거나 AI_ENABLED=False 면 키워드 방식으로 무중단 폴백.
# ----------------------------------------------------------------------------
def _load_anthropic_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        key_file = os.path.join(BASE_DIR, "anthropic_key.txt")
        if os.path.exists(key_file):
            with open(key_file, encoding="utf-8") as f:
                key = f.read().strip()
    return key


ANTHROPIC_API_KEY = _load_anthropic_key()

AI_ENABLED = True                       # False 면 AI 끄고 키워드 방식만 사용
AI_MODEL = "claude-haiku-4-5"           # 분류용 최저가 모델. 필요시 claude-sonnet-4-6 등으로 교체
AI_MAX_BODY_CHARS = 1500                # 판단에 넘길 본문 최대 길이(토큰·비용 절약)
AI_RELEVANT_SCORE = 50                  # 이 점수 이상이면 관련 공고로 저장

# 비용 통제 — 이달 누적 추정 비용이 한도에 도달하면 그달 남은 기간 AI 중지(키워드 폴백)
AI_MONTHLY_BUDGET_KRW = 6000

# Claude Haiku 4.5 단가 (100만 토큰당 USD) — 비용 추정용
AI_PRICE_INPUT_PER_1M = 1.0
AI_PRICE_OUTPUT_PER_1M = 5.0
USD_TO_KRW = 1400                       # 대략 환율(추정용)

# AI 판단 프롬프트에 쓰는 회사 비전
COMPANY_VISION = """세이렌어쿠스틱스는 두 가지 핵심 서비스를 개발하는 회사입니다.
1. 층간소음을 주거환경에서 모니터링할 수 있는 서비스 (CARE)
2. 능동 진동·소음 제어 기술로 주거환경을 개선하는 서비스 (MUTER)
주거 공간의 소음·진동 문제 해결과 거주환경 품질 향상이 핵심 미션입니다.
음향, 진동, 소음 제어, 센서, 신호처리, 스마트홈, 공동주택 환경 분야가 관련 깊습니다."""
