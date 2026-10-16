from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from pagewatch.jobqueue import reset_stuck_jobs, enqueue_job
from pagewatch.db import run_query
from pagewatch.digest import send_daily_digests

_scheduler = None


def scheduler_tick():
    reset_stuck_jobs()

    now_iso = datetime.now(timezone.utc).isoformat()
    due_urls = run_query(
        """
        SELECT url_id
        FROM monitors
        WHERE is_active = 1 AND (next_check_at IS NULL OR next_check_at <= ?)
        GROUP BY url_id
        """,
        (now_iso,)
    )

    for row in due_urls:
        enqueue_job(row["url_id"])


def start_scheduler():
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        scheduler_tick,
        trigger="interval",
        seconds=30,
        id="scheduler_tick",
        replace_existing=True,
    )
    _scheduler.add_job(
        send_daily_digests,
        trigger="cron",
        hour=9,
        minute=0,
        id="daily_digest",
        replace_existing=True,
    )
    _scheduler.start()
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def is_scheduler_running():
    return bool(_scheduler is not None and _scheduler.running)
