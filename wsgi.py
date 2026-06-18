"""
WSGI 진입점 (운영 배포용).

gunicorn 은 `python app.py` 의 __main__ 블록을 실행하지 않으므로, 여기서 bootstrap()
(DB 초기화 + 스케줄러 기동)을 호출한 뒤 app 객체를 노출한다.

실행 예 (Oracle Linux/Ubuntu):
    gunicorn --workers 1 --threads 4 --bind 0.0.0.0:5000 wsgi:app

※ 반드시 --workers 1 로 띄운다. 워커가 여러 개면 스케줄러가 중복 기동돼
  자동 수집이 여러 번 실행된다(1코어 free tier 에도 워커 1개가 적절).
"""

from app import app, bootstrap

# 단일 워커 프로세스에서 1회 실행 — DB 초기화 + 매일 08:00 스케줄러 등록
bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
