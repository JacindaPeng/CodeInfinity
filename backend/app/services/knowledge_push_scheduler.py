"""知识推送定时任务（APScheduler）。"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from ..config import settings
from ..database import SessionLocal

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job_daily_push() -> None:
    from .knowledge_push_service import run_daily_knowledge_push

    db = SessionLocal()
    try:
        result = run_daily_knowledge_push(db, fetch=True)
        logger.info("knowledge push cron: %s", result)
    except Exception:
        logger.exception("knowledge push cron failed")
    finally:
        db.close()


def start_knowledge_push_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    hour = max(0, min(23, int(settings.knowledge_push_hour)))
    minute = max(0, min(59, int(settings.knowledge_push_minute)))
    _scheduler.add_job(
        _job_daily_push,
        "cron",
        hour=hour,
        minute=minute,
        id="daily_knowledge_push",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("knowledge push scheduler started at %02d:%02d", hour, minute)


def stop_knowledge_push_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        pass
    _scheduler = None
