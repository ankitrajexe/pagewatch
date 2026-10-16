import os
import random
import threading
import time
from datetime import datetime, timezone, timedelta

from pagewatch import config
from pagewatch.fetcher import BrowserSession
from pagewatch.jobqueue import claim_next_job, finish_job, fail_job
from pagewatch.checker import check_monitor
from pagewatch.failures import classify_fetch
from pagewatch.ratelimit import wait_for_domain, is_allowed_by_robots, apply_backoff
from pagewatch.alerts import notify_status
from pagewatch.db import run_query, run_write


class Worker:
    def __init__(self):
        self._thread = None
        self._running = False
        self._browser_session = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="PageWatchWorker", daemon=True)
        self._thread.start()

    def stop(self, timeout_seconds=5):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout_seconds)

    def _run_loop(self):
        while self._running:
            self._browser_session = BrowserSession()
            try:
                self._browser_session.start()
            except Exception as err:
                print(f"worker: failed to start browser: {err}")
                time.sleep(5)
                continue

            try:
                while self._running:
                    try:
                        job = claim_next_job()
                    except Exception as err:
                        print(f"worker: error claiming job: {err}")
                        time.sleep(2)
                        continue

                    if not job:
                        time.sleep(2)
                        continue

                    self._process_job(job)
            except Exception as fatal_err:
                print(f"worker: crash, restarting session: {fatal_err}")
                time.sleep(2)
            finally:
                if self._browser_session:
                    try:
                        self._browser_session.stop()
                    except Exception:
                        pass
                    self._browser_session = None

    def _process_job(self, job):
        job = dict(job)
        job_id = job["id"]
        job_type = job.get("job_type", "check")

        if job_type == "picker_snapshot":
            self._process_picker_job(job)
            return

        url_id = job["url_id"]
        job_monitor_id = job.get("monitor_id")

        try:
            url_rows = run_query("SELECT * FROM urls WHERE id = ?", (url_id,))
            if not url_rows:
                finish_job(job_id)
                return

            url_row = url_rows[0]
            target_url = url_row["url"]
            domain = url_row["domain"]

            now_iso = datetime.now(timezone.utc).isoformat()
            if job_monitor_id:
                monitors = run_query(
                    "SELECT * FROM monitors WHERE id = ? AND is_active = 1",
                    (job_monitor_id,)
                )
            else:
                monitors = run_query(
                    """
                    SELECT * FROM monitors
                    WHERE url_id = ? AND is_active = 1 AND (next_check_at IS NULL OR next_check_at <= ?)
                    """,
                    (url_id, now_iso)
                )

            if not monitors:
                finish_job(job_id)
                return

            if not is_allowed_by_robots(target_url):
                self._handle_robots_disallowed(monitors, job_id)
                return

            blocked_until = url_row["blocked_until"]
            now = datetime.now(timezone.utc)
            if blocked_until:
                try:
                    blocked_dt = datetime.fromisoformat(blocked_until)
                    if blocked_dt.tzinfo is None:
                        blocked_dt = blocked_dt.replace(tzinfo=timezone.utc)
                    if blocked_dt > now:
                        run_write(
                            """
                            UPDATE jobs
                            SET status = 'queued', run_after = ?
                            WHERE id = ?
                            """,
                            (blocked_until, job_id)
                        )
                        return
                except Exception:
                    pass

            wait_for_domain(domain, is_running_callback=lambda: self._running)
            if not self._running:
                return

            fetch_result = self._browser_session.fetch_page(
                target_url,
                timeout_seconds=config.PAGE_TIMEOUT_SECONDS
            )

            now_iso = datetime.now(timezone.utc).isoformat()
            http_status = fetch_result.get("http_status")
            run_write(
                """
                UPDATE urls
                SET last_fetched_at = ?, last_http_status = ?
                WHERE id = ?
                """,
                (now_iso, http_status, url_id)
            )

            if http_status in (429, 503):
                apply_backoff(url_id)

            classification = classify_fetch(fetch_result)
            outcome = classification["outcome"]
            outcome_message = classification["message"]

            if outcome != "ok":
                self._handle_failure_outcome(
                    monitors,
                    outcome,
                    outcome_message,
                    http_status,
                    fetch_result.get("duration_ms", 0)
                )
                if fetch_result.get("error_type") == "timeout":
                    fail_job(job_id, outcome_message)
                else:
                    finish_job(job_id)
                return

            run_write("UPDATE urls SET consecutive_failures = 0 WHERE id = ?", (url_id,))
            for monitor in monitors:
                try:
                    check_monitor(monitor, fetch_result)
                except Exception as err:
                    print(f"worker: error checking monitor {monitor['id']}: {err}")

            finish_job(job_id)
        except Exception as err:
            print(f"worker: job {job_id} unexpected error: {err}")
            fail_job(job_id, str(err))

    def _handle_robots_disallowed(self, monitors, job_id):
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        msg = "robots.txt disallows this URL"

        for monitor in monitors:
            monitor = dict(monitor)
            failures = int(monitor.get("consecutive_failures", 0)) + 1
            interval = int(monitor.get("interval_minutes", 60))
            jitter = random.randint(0, 60)
            next_iso = (now + timedelta(minutes=interval, seconds=jitter)).isoformat()

            run_write(
                """
                UPDATE monitors
                SET status = 'blocked', status_message = ?, consecutive_failures = ?,
                    last_checked_at = ?, next_check_at = ?
                WHERE id = ?
                """,
                (msg, failures, now_iso, next_iso, monitor["id"])
            )
            run_write(
                """
                INSERT INTO check_log (monitor_id, checked_at, outcome, message, http_status, duration_ms)
                VALUES (?, ?, 'blocked', ?, NULL, 0)
                """,
                (monitor["id"], now_iso, msg)
            )
            if failures == 3:
                notify_status(monitor, "blocked", msg)

        finish_job(job_id)

    def _handle_failure_outcome(self, monitors, outcome, message, http_status, duration_ms):
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        for monitor in monitors:
            monitor = dict(monitor)
            failures = int(monitor.get("consecutive_failures", 0)) + 1
            interval = int(monitor.get("interval_minutes", 60))
            jitter = random.randint(0, 60)
            next_iso = (now + timedelta(minutes=interval, seconds=jitter)).isoformat()

            run_write(
                """
                UPDATE monitors
                SET status = ?, status_message = ?, consecutive_failures = ?,
                    last_checked_at = ?, next_check_at = ?
                WHERE id = ?
                """,
                (outcome, message, failures, now_iso, next_iso, monitor["id"])
            )
            run_write(
                """
                INSERT INTO check_log (monitor_id, checked_at, outcome, message, http_status, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (monitor["id"], now_iso, outcome, message, http_status, duration_ms)
            )
            if failures == 3:
                status_kind = "blocked" if outcome == "blocked" else "down"
                notify_status(monitor, status_kind, message)

    def _process_picker_job(self, job):
        job_id = job["id"]
        url_id = job["url_id"]
        monitor_id = job.get("monitor_id")

        try:
            url_rows = run_query("SELECT * FROM urls WHERE id = ?", (url_id,))
            if not url_rows:
                finish_job(job_id)
                return

            target_url = url_rows[0]["url"]
            out_png = os.path.join(config.PICKER_DIR, f"monitor_{monitor_id}.png")
            out_json = os.path.join(config.PICKER_DIR, f"monitor_{monitor_id}.json")

            from pagewatch.picker import capture_picker_snapshot
            capture_picker_snapshot(
                self._browser_session,
                target_url,
                monitor_id,
                out_png,
                out_json,
                timeout_seconds=config.PAGE_TIMEOUT_SECONDS,
            )
            finish_job(job_id)
        except Exception as err:
            print(f"worker: picker snapshot job {job_id} failed: {err}")
            fail_job(job_id, str(err))
