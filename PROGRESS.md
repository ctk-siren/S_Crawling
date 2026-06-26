# 세이렌 크롤링 대시보드 — 진행 노트

> SA-STD-001 원칙 6(맥락 영속화)에 따라 진행·결정을 기록한다.
> 세션이 끊겨도 이 파일로 맥락을 이어간다.

## 목표
매일 오전 8시 5개 정부 사이트 공고를 수집 → 회사 키워드 매칭 → 대시보드 표시.
핫딜 페이지에서 사용자 키워드의 쇼핑 가격 표시. **외부 유료 API 사용 안 함(운영비 0원).**

## 결정 사항
- v2: AI 판단 제거, 순수 키워드 매칭(제목+본문, 대소문자 무시).
- 핫딜 대상: 네이버 쇼핑 검색(기본), 함수 분리로 추후 확장.
- 사이트별 크롤러 플러그인 구조, NTIS부터 실제 동작 확인.
- 개발: Windows 로컬 / 운영: Oracle Linux. 경로·스케줄러 양쪽 호환.

## 단계 진행 상황
- [완료] 1~4. 기반 파일(폴더, requirements.txt, config.py, database.py) + DB 초기화 검증
  - 검증 결과 — 테이블 5개(announcements/keywords/hotdeal_keywords/hotdeals/meta) 생성, 키워드 13개(core 5) 시드 확인
- [완료] 5. crawler.py (NTIS 우선)
  - NTIS 라이브 파싱 검증 완료(table.basic_list, 10건/페이지). 제목 '공고명_(연도)사업명' 중복 정리.
  - 매칭→저장→조회 파이프라인 mock 검증 완료(대소문자 무시, 부분일치).
  - g2b/smtech/iris/kstartup 은 stub(빈 리스트), 순차 구현 예정.
  - **핫딜 해결** — 멀티소스 구조. 다나와·에누리 라이브 검증(각 10건, 총 20건). 소스별 try/except 격리.
    네이버 쇼핑은 봇 차단(418)으로 빈 리스트(추후 무료 Open API 발급 시 _hotdeal_naver 구현).
- [완료] 6. scheduler.py
  - BackgroundScheduler(Asia/Seoul), cron 매일 08:00 daily_crawl 등록 검증. max_instances=1, coalesce=True.
  - app.py 에서 start_scheduler() 호출 예정. 예외는 scheduled_crawl 래퍼에서 흡수.
- [완료] 7. app.py
  - 페이지 2개(/, /hotdeal) + API(키워드 add/del, 핫딜 add/del/refresh, 수동 crawl). 응답규약 {ok:...}.
  - bootstrap()에서 init_db+start_scheduler. app.run use_reloader=False(스케줄러 중복 방지).
- [완료] 8. templates/index.html — 공고 카드, 키워드 칩 관리, 마지막 수집 시각, NEW 뱃지, 지금 수집.
- [완료] 9. templates/hotdeal.html — 키워드 등록(즉시 수집), 키워드별 카드(가격/링크), 재검색·삭제.
- [완료] 10. static/style.css — 공통 스타일(카드/칩/뱃지/2페이지 네비).
- [완료] 통합 검증
  - 테스트 클라이언트: GET / · /hotdeal 200, 키워드 add/del 200, 수동 crawl 200.
  - 임시 키워드('기술개발')로 카드 렌더·매칭태그·NEW 뱃지·2건 저장 확인 후 정리(DB 원복).
  - 핫딜 등록 라이브 20건 수집·가격 카드 렌더 확인 후 정리.
  - python app.py 실서버 기동: 두 페이지 200, 스케줄러 정상 기동 로그 확인.

## 추가 진행 (2026-06-18 이어서)
- [완료] smtech 크롤러 — caption '사업공고 목록' 테이블 파싱(15건). 세션ID 제거. IRIS 위탁공고(goMove())는 목록URL로 폴백.
- [완료] k-startup 크롤러 — li.notice 파싱(15건). go_view(pbancSn)→상세URL(schM=view&pbancSn=). 마감일자 정규식 추출.
- 전체 run_crawl 통합 검증 — NTIS10+smtech15+kstartup15=40건, 오류 0(검증 후 실데이터 정리).
- [결정] g2b·iris — 공공데이터포털 data.go.kr 무료 Open API 사용으로 확정(사용자 선택).
- [코드작성/검증대기] g2b·iris Open API 클라이언트 작성 완료(crawler.py). 서비스키는 환경변수 DATA_GO_KR_SERVICE_KEY 로 주입.
    - g2b: 조달청 나라장터 입찰공고정보서비스(15129394) getBidPblancListInfoServc(용역), 최근 G2B_LOOKBACK_DAYS일.
    - iris: 과기부 사업공고(15074634) businessAnnouncMentList. ※ 과기부 피드라 산업부 IRIS와 정확히 일치하진 않음.
    - 키 없으면 빈 리스트로 graceful. 응답 필드명은 문서 기준 추정 → **키 발급 후 실제 응답으로 검증·조정 필요.**

- [완료] g2b·iris Open API 검증 완료(서비스키 활성화 후).
    - 키 이중 인코딩은 config unquote로 해결. g2b는 /ad/ 차세대 경로 사용.
    - g2b: response.body.items 리스트. bidNtceNm/bidClseDt/ntceInsttNm/bidNtceDtlUrl/asignBdgtAmt(예산). 30건/회.
    - iris(MSIT): response=[{header},{body}], items 각 원소 {'item':{...}}. subject/viewUrl/deptName. 마감일 필드 없음. 10건/회.
    - 전체 5사이트 run_crawl 통합: NTIS10+g2b30+smtech15+iris10+kstartup15=80건, 오류 0. 매칭→저장→표시 경로 검증 후 정리.

- [완료] NTIS 상세 페이지 보강 — div.notice_area에서 공고금액(지원규모)·공고내용(본문) 추출.
    - 본문을 매칭 대상에 포함(제목에 없고 본문에만 있는 키워드도 매칭). 지원규모 '117.32억원' 형태로 표시.
    - config.NTIS_FETCH_DETAIL 토글, 상세 요청 사이 0.3초 지연. 목록 ~10건이라 상세도 ~10요청/회.
    - 전체 run_crawl 80건 17.5초(상세 보강 ~9초 포함), 오류 0.

- [완료] Oracle 배포 실제 수행 — Ubuntu 인스턴스(Osaka), systemd 상시 실행, 포트 5000 개방, 접속 확인.
    배포 중 수정: siren.service 경로 S_Crawling, iptables는 REJECT보다 위에 삽입해야 함(DEPLOY.md 반영).
- [완료] 운영 보정 — 시간 KST 표시(database.KST), g2b/iris API 타임아웃 30초로 상향(data.go.kr ReadTimeout 대응).

- [완료] 공고 대시보드 왼쪽 사이드바(수집 사이트 5곳 + 사이트별 공고 수) 추가.
- [완료] 마감 지난 공고 자동 숨김 — get_announcements(only_open=True). 마감일 형식 통일 파싱(_deadline_passed).
    마감일 없는 IRIS 글은 판단 불가라 유지(숨기면 IRIS 통째로 사라짐).

## AI 관련도 판단 기능 (2026-06-26 추가)
- [완료] ai_filter.py — Claude(Haiku 4.5) structured output으로 관련도(relevant/score/reason) 판단. 키 없거나 실패 시 None(폴백).
- [완료] config — ANTHROPIC_API_KEY(env/anthropic_key.txt), AI_ENABLED, AI_MODEL, AI_MONTHLY_BUDGET_KRW(6000), 단가·비전.
- [완료] database — ai_judgments 캐시 테이블, announcements ai_relevant/ai_score/ai_reason 컬럼(ALTER 마이그레이션),
    월별 비용 meta(add_ai_spend/get_ai_spend), get_announcements(only_relevant=).
- [완료] crawler.run_crawl — 신규 URL만 AI 호출(캐시 재사용), 월예산 초과 시 키워드 폴백, summary에 ai_calls·ai_cost_krw.
- [완료] UI — 대시보드는 관련 공고만(only_relevant), 카드에 AI 이유·관련도 배지, 사이드바에 이달 AI 비용.
- 검증(mock): 키워드 없는 '바닥충격음' 공고도 AI가 관련(80) 판정·저장, 무관 제외, 캐시 재사용·예산0 폴백, 키없음 무중단 모두 확인.
- [검증대기] **실제 Claude API 호출**은 ANTHROPIC_API_KEY 발급 후 라이브 검증 필요. 기본 AI_ENABLED=True지만 키 없으면 자동으로 키워드 모드.
- 비용 통제: 앱 월 상한(6000원, 초과 시 폴백) + Anthropic Console 하드 한도(사용자 설정 권장).

## 메모 / 미해결 (확인·후속 필요 — 비워두고 진행)
- [ ] IRIS(과기부 API)는 마감일 필드가 없어 '선정결과' 등 비공모 글이 섞일 수 있음(마감 필터로 못 거름).
- [ ] g2b는 용역(service) 입찰만 수집. 필요 시 공사/물품 오퍼레이션 추가 가능.
- [ ] iris=과기부 사업공고 API 대체. 산업부 전용 IRIS 공고가 꼭 필요하면 별도 소스 검토.
- [ ] (선택) g2b·iris·smtech·kstartup도 상세 본문 보강 가능하나 현재는 제목/요약 매칭으로 충분.
- [완료] Oracle 배포 준비 파일 작성 — wsgi.py(gunicorn 진입점, bootstrap로 스케줄러 기동),
    requirements-deploy.txt(gunicorn), siren.service(systemd), DEPLOY.md(단계별 가이드).
    핵심: gunicorn은 __main__ 미실행 → wsgi.py에서 bootstrap 호출. --workers 1 필수(스케줄러 중복 방지).
    실제 서버 접속·방화벽(OCI Security List + 인스턴스 firewall)·systemd 등록은 사용자가 DEPLOY.md 따라 수행.
- [ ] (사용자 작업) GitHub Private 저장소 생성·푸시 후 서버에서 git clone. 현재 로컬은 아직 git init 안 됨.
- [ ] iris를 과기부 사업공고 API로 대체한 점 — 산업부 IRIS가 꼭 필요하면 별도 소스 검토.
- [ ] NTIS 상세 페이지 보강 — 지원규모(fund_scale)·본문 매칭이 필요하면 상세 페이지 추가 수집(서버 부하 고려).
- [ ] 핫딜 네이버 쇼핑 — 무료 Open API(client id/secret) 발급 시 _hotdeal_naver 구현.
- [ ] 배포 — Oracle Linux에서는 개발서버(Flask) 대신 gunicorn 등 WSGI 권장. 방화벽/포트(5000) 개방, systemd 등록.
- 정부/쇼핑 사이트 셀렉터는 사이트 개편 시 깨질 수 있어 주기적 점검 필요.
