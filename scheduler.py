"""
자동 수집 스케줄러.

매일 config.SCHEDULE_HOUR:SCHEDULE_MINUTE(기본 08:00)에 run_crawl() 을 실행한다.
Flask 앱(app.py)에서 start_scheduler() 를 호출해 백그라운드로 기동한다.

설계 메모
  - BackgroundScheduler 를 쓰므로 Flask 메인 스레드를 막지 않는다.
  - 잡 실행이 겹치지 않도록 max_instances=1, 누락 시 합치도록 coalesce=True.
  - Oracle Linux·Windows 양쪽에서 동작하도록 표준 cron 트리거만 사용한다.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

import config
from crawler import run_crawl

logger = logging.getLogger(__name__)

_scheduler = None  # 단일 인스턴스 보관


def scheduled_crawl():
    """스케줄러가 호출하는 래퍼. 예외가 스케줄러를 죽이지 않도록 감싼다."""
    logger.info("자동 수집 시작")
    try:
        summary = run_crawl()
        logger.info(
            "자동 수집 완료 — 수집 %s건, 매칭 %s건, 신규저장 %s건",
            summary["fetched"], summary["matched"], summary["saved"],
        )
        if summary["errors"]:
            logger.warning("일부 사이트 오류: %s", summary["errors"])
    except Exception:
        logger.exception("자동 수집 중 예외 발생")


def start_scheduler():
    """스케줄러를 한 번만 생성·기동하고 인스턴스를 반환한다."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        scheduled_crawl,
        trigger="cron",
        hour=config.SCHEDULE_HOUR,
        minute=config.SCHEDULE_MINUTE,
        id="daily_crawl",
        max_instances=1,   # 이전 실행이 안 끝났으면 중복 실행 안 함
        coalesce=True,      # 누락된 실행은 한 번으로 합침
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "스케줄러 기동 — 매일 %02d:%02d 자동 수집 등록",
        config.SCHEDULE_HOUR, config.SCHEDULE_MINUTE,
    )
    _scheduler = scheduler
    return scheduler


if __name__ == "__main__":
    # 단독 실행 — 등록된 잡과 다음 실행 시각 확인
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    sched = start_scheduler()
    for job in sched.get_jobs():
        print(f"잡 등록 확인 - id={job.id}, 다음 실행={job.next_run_time}")
    sched.shutdown()
