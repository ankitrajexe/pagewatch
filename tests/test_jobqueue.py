# tests/test_jobqueue.py
# -----------------------
# What it does: Unit tests for SQLite job queue operations (enqueue, atomic claim,
#               finish, retries with backoff, and stuck job recovery).
# Talks to: pagewatch/jobqueue.py, pagewatch/db.py

import pytest
from datetime import datetime, timezone, timedelta
from pagewatch import config
from pagewatch.db import create_tables, run_query, run_write
from pagewatch.jobqueue import (
    enqueue_job,
    claim_next_job,
    finish_job,
    fail_job,
    reset_stuck_jobs,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Set up temporary database for queue tests."""
    db_file = str(tmp_path / "jobqueue_test.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr("pagewatch.db.DB_PATH", db_file)
    create_tables()

    # Insert a dummy URL row so foreign keys are satisfied
    run_write("INSERT INTO urls (id, url, domain) VALUES (1, 'http://test.local', 'test.local')")


class TestJobQueue:
    """Tests for jobqueue functions."""

    def test_enqueue_and_deduplicate(self):
        """Enqueueing for a URL works, but duplicate while queued/running returns None."""
        job_id = enqueue_job(1)
        assert job_id is not None

        # Trying to enqueue for same URL again while queued returns None
        assert enqueue_job(1) is None

        # Claim the job (now it is 'running')
        claimed = claim_next_job()
        assert claimed is not None
        assert claimed["id"] == job_id

        # Trying to enqueue while running still returns None
        assert enqueue_job(1) is None

        # Finish the job
        finish_job(job_id)

        # Now enqueueing works again!
        new_job_id = enqueue_job(1)
        assert new_job_id is not None
        assert new_job_id != job_id

    def test_claim_next_job_respects_run_after(self):
        """Jobs scheduled for the future are not claimed until due."""
        future_iso = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        job_id = run_write(
            "INSERT INTO jobs (url_id, status, run_after, created_at) VALUES (1, 'queued', ?, ?)",
            (future_iso, future_iso)
        )

        assert claim_next_job() is None

        # Update run_after to past
        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        run_write("UPDATE jobs SET run_after = ? WHERE id = ?", (past_iso, job_id))

        claimed = claim_next_job()
        assert claimed is not None
        assert claimed["id"] == job_id
        assert claimed["status"] == "running"
        assert claimed["attempts"] == 1

    def test_fail_job_retries_and_exponential_backoff(self, monkeypatch):
        """Job retries with backoff up to MAX_RETRIES, then marks failed."""
        monkeypatch.setattr(config, "MAX_RETRIES", 3)
        job_id = enqueue_job(1)

        # Attempt 1
        claim_next_job()
        fail_job(job_id, "Error 1")
        job = run_query("SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
        assert job["status"] == "queued"
        assert job["attempts"] == 1
        assert "Error 1" in job["error"]

        # Attempt 2
        run_write("UPDATE jobs SET run_after = NULL WHERE id = ?", (job_id,))
        claim_next_job()
        fail_job(job_id, "Error 2")
        job = run_query("SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
        assert job["status"] == "queued"
        assert job["attempts"] == 2

        # Attempt 3 (final attempt)
        run_write("UPDATE jobs SET run_after = NULL WHERE id = ?", (job_id,))
        claim_next_job()
        fail_job(job_id, "Error 3")
        job = run_query("SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
        assert job["status"] == "failed"
        assert job["attempts"] == 3
        assert job["finished_at"] is not None

    def test_reset_stuck_jobs(self):
        """Jobs running for > 5 minutes are reset to queued."""
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        run_write(
            "INSERT INTO jobs (url_id, status, started_at, created_at) VALUES (1, 'running', ?, ?)",
            (old_time, old_time)
        )

        # Recent running job (< 5 min)
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        run_write(
            "INSERT INTO jobs (url_id, status, started_at, created_at) VALUES (1, 'running', ?, ?)",
            (recent_time, recent_time)
        )

        reset_count = reset_stuck_jobs(stuck_minutes=5)
        assert reset_count == 1

        rows = run_query("SELECT status FROM jobs ORDER BY id ASC")
        assert rows[0]["status"] == "queued"
        assert rows[1]["status"] == "running"
