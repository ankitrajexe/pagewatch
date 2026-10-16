# tests/test_scheduler.py
# -----------------------
# What it does: Unit tests for APScheduler periodic checks, monitor deduplication,
#               and stuck job recovery inside scheduler_tick.
# Talks to: pagewatch/scheduler.py, pagewatch/jobqueue.py, pagewatch/db.py

import pytest
from datetime import datetime, timezone, timedelta
from pagewatch import config
from pagewatch.db import create_tables, run_query, run_write
from pagewatch.scheduler import (
    scheduler_tick,
    start_scheduler,
    stop_scheduler,
    is_scheduler_running,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Set up temporary database for scheduler tests and ensure scheduler is stopped."""
    db_file = str(tmp_path / "scheduler_test.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr("pagewatch.db.DB_PATH", db_file)
    create_tables()

    # Ensure background scheduler is stopped before and after test
    stop_scheduler()
    yield
    stop_scheduler()


class TestScheduler:
    """Tests for scheduler_tick and scheduler lifecycle."""

    def test_three_monitors_on_same_url_produce_one_queued_job(self):
        """
        When 3 monitors point to the same URL and all are due,
        scheduler_tick enqueues exactly 1 job for that URL.
        """
        # Insert shared URL
        url_id = run_write(
            "INSERT INTO urls (url, domain) VALUES (?, ?)",
            ("http://example.com/shared", "example.com")
        )

        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Insert 3 monitors pointing to the same url_id
        for i in range(1, 4):
            run_write(
                """
                INSERT INTO monitors (
                    name, url_id, interval_minutes, sensitivity,
                    next_check_at, is_active, created_at
                ) VALUES (?, ?, 15, 'medium', ?, 1, ?)
                """,
                (f"Monitor {i}", url_id, past_iso, now_iso)
            )

        # Run scheduler tick
        scheduler_tick()

        # Check jobs table
        jobs = run_query("SELECT * FROM jobs WHERE status = 'queued'")
        assert len(jobs) == 1
        assert jobs[0]["url_id"] == url_id

    def test_future_monitor_produces_zero_queued_jobs(self):
        """
        A monitor whose next_check_at is in the future produces 0 queued jobs.
        """
        url_id = run_write(
            "INSERT INTO urls (url, domain) VALUES (?, ?)",
            ("http://example.com/future", "example.com")
        )

        future_iso = (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        run_write(
            """
            INSERT INTO monitors (
                name, url_id, interval_minutes, sensitivity,
                next_check_at, is_active, created_at
            ) VALUES ('Future Monitor', ?, 60, 'medium', ?, 1, ?)
            """,
            (url_id, future_iso, now_iso)
        )

        # Run scheduler tick
        scheduler_tick()

        jobs = run_query("SELECT * FROM jobs WHERE status = 'queued'")
        assert len(jobs) == 0

    def test_stuck_job_reset_in_scheduler_tick(self):
        """
        Any job running for > 5 minutes is reset back to 'queued' by scheduler_tick.
        """
        url_id = run_write(
            "INSERT INTO urls (url, domain) VALUES (?, ?)",
            ("http://example.com/stuck", "example.com")
        )

        ten_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        job_id = run_write(
            """
            INSERT INTO jobs (url_id, status, attempts, started_at, created_at)
            VALUES (?, 'running', 1, ?, ?)
            """,
            (url_id, ten_min_ago, ten_min_ago)
        )

        # Run tick (which calls reset_stuck_jobs)
        scheduler_tick()

        row = run_query("SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
        assert row["status"] == "queued"

    def test_inactive_monitors_are_not_queued(self):
        """
        Monitors with is_active = 0 are ignored by scheduler_tick even if next_check_at is in the past.
        """
        url_id = run_write(
            "INSERT INTO urls (url, domain) VALUES (?, ?)",
            ("http://example.com/inactive", "example.com")
        )

        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        run_write(
            """
            INSERT INTO monitors (
                name, url_id, interval_minutes, sensitivity,
                next_check_at, is_active, created_at
            ) VALUES ('Inactive Monitor', ?, 15, 'medium', ?, 0, ?)
            """,
            (url_id, past_iso, now_iso)
        )

        scheduler_tick()

        jobs = run_query("SELECT * FROM jobs WHERE status = 'queued'")
        assert len(jobs) == 0

    def test_multiple_due_urls_each_get_a_job(self):
        """
        Monitors on different URLs each get their own queued job.
        """
        url1_id = run_write(
            "INSERT INTO urls (url, domain) VALUES (?, ?)",
            ("http://site1.com", "site1.com")
        )
        url2_id = run_write(
            "INSERT INTO urls (url, domain) VALUES (?, ?)",
            ("http://site2.com", "site2.com")
        )

        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        run_write(
            "INSERT INTO monitors (name, url_id, interval_minutes, next_check_at, is_active, created_at) VALUES (?, ?, 15, ?, 1, ?)",
            ("M1", url1_id, past_iso, now_iso)
        )
        run_write(
            "INSERT INTO monitors (name, url_id, interval_minutes, next_check_at, is_active, created_at) VALUES (?, ?, 15, ?, 1, ?)",
            ("M2", url2_id, past_iso, now_iso)
        )

        scheduler_tick()

        jobs = run_query("SELECT * FROM jobs WHERE status = 'queued' ORDER BY url_id ASC")
        assert len(jobs) == 2
        assert jobs[0]["url_id"] == url1_id
        assert jobs[1]["url_id"] == url2_id

    def test_scheduler_start_and_stop_lifecycle(self):
        """
        start_scheduler starts the APScheduler background thread,
        and stop_scheduler shuts it down.
        """
        assert is_scheduler_running() is False

        sched = start_scheduler()
        assert sched is not None
        assert is_scheduler_running() is True

        stop_scheduler()
        assert is_scheduler_running() is False

    def test_worker_only_checks_due_monitors_for_url(self, monkeypatch):
        """
        When a URL has two monitors (one due, one future),
        a periodic job (monitor_id=None) only checks the due monitor.
        """
        from pagewatch.worker import Worker
        from pagewatch.jobqueue import enqueue_job, claim_next_job

        url_id = run_write(
            "INSERT INTO urls (url, domain) VALUES (?, ?)",
            ("http://example.com/selective", "example.com")
        )

        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        future_iso = (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        m1_id = run_write(
            "INSERT INTO monitors (name, url_id, interval_minutes, next_check_at, is_active, created_at) VALUES (?, ?, 15, ?, 1, ?)",
            ("Due Monitor", url_id, past_iso, now_iso)
        )
        m2_id = run_write(
            "INSERT INTO monitors (name, url_id, interval_minutes, next_check_at, is_active, created_at) VALUES (?, ?, 60, ?, 1, ?)",
            ("Future Monitor", url_id, future_iso, now_iso)
        )

        checked_monitors = []
        monkeypatch.setattr("pagewatch.worker.check_monitor", lambda mon, fetch_res: checked_monitors.append(mon["id"]))
        monkeypatch.setattr("pagewatch.worker.is_allowed_by_robots", lambda url: True)
        monkeypatch.setattr("pagewatch.worker.wait_for_domain", lambda domain, **kwargs: None)

        worker = Worker()
        worker._running = True
        class FakeBrowser:
            def fetch_page(self, url, timeout_seconds):
                return {
                    "ok": True,
                    "http_status": 200,
                    "final_url": url,
                    "html": "<html><body>Hello</body></html>",
                    "page_text": "This is a valid test page with plenty of text.",
                    "screenshot_bytes": b"fake",
                    "error_type": None,
                    "error_message": None,
                    "duration_ms": 100,
                }
        worker._browser_session = FakeBrowser()

        # Enqueue periodic job (monitor_id is None)
        job_id = enqueue_job(url_id, monitor_id=None)
        job = claim_next_job()
        worker._process_job(job)

        # Only m1 was checked; m2 was not due!
        assert checked_monitors == [m1_id]

    def test_worker_checks_explicit_monitor_even_if_future(self, monkeypatch):
        """
        When 'Check now' enqueues a job with monitor_id set,
        the worker checks that monitor even if its next_check_at is in the future.
        """
        from pagewatch.worker import Worker
        from pagewatch.jobqueue import enqueue_job, claim_next_job

        url_id = run_write(
            "INSERT INTO urls (url, domain) VALUES (?, ?)",
            ("http://example.com/future-check", "example.com")
        )

        future_iso = (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        m_id = run_write(
            "INSERT INTO monitors (name, url_id, interval_minutes, next_check_at, is_active, created_at) VALUES (?, ?, 60, ?, 1, ?)",
            ("Future Monitor", url_id, future_iso, now_iso)
        )

        checked_monitors = []
        monkeypatch.setattr("pagewatch.worker.check_monitor", lambda mon, fetch_res: checked_monitors.append(mon["id"]))
        monkeypatch.setattr("pagewatch.worker.is_allowed_by_robots", lambda url: True)
        monkeypatch.setattr("pagewatch.worker.wait_for_domain", lambda domain, **kwargs: None)

        worker = Worker()
        worker._running = True
        class FakeBrowser:
            def fetch_page(self, url, timeout_seconds):
                return {
                    "ok": True,
                    "http_status": 200,
                    "final_url": url,
                    "html": "<html><body>Hello</body></html>",
                    "page_text": "This is a valid test page with plenty of text.",
                    "screenshot_bytes": b"fake",
                    "error_type": None,
                    "error_message": None,
                    "duration_ms": 100,
                }
        worker._browser_session = FakeBrowser()

        # Enqueue explicit monitor job (as check_now does)
        job_id = enqueue_job(url_id, monitor_id=m_id)
        job = claim_next_job()
        worker._process_job(job)

        assert checked_monitors == [m_id]

    def test_dev_fast_mode_dropdown(self, monkeypatch):
        """
        When DEV_FAST_MODE is True, get_interval_choices provides 1 min and 2 min options.
        """
        from pagewatch.web.routes import get_interval_choices

        monkeypatch.setattr(config, "DEV_FAST_MODE", False)
        standard_intervals = [mins for mins, label in get_interval_choices()]
        assert 1 not in standard_intervals
        assert 2 not in standard_intervals

        monkeypatch.setattr(config, "DEV_FAST_MODE", True)
        fast_intervals = [mins for mins, label in get_interval_choices()]
        assert 1 in fast_intervals
        assert 2 in fast_intervals

    def test_dashboard_status_panel_stats(self, monkeypatch):
        """
        Dashboard route renders scheduler running status and job counts in footer.
        """
        from pagewatch.web.routes import bp
        from flask import Flask

        app = Flask(__name__, template_folder="../pagewatch/web/templates")
        app.secret_key = "test"
        app.register_blueprint(bp)
        client = app.test_client()

        res = client.get("/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Scheduler" in html
        assert "Queued Jobs" in html
        assert "Running Jobs" in html
        assert "Failed (Last 24h)" in html
