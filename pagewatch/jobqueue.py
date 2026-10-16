from datetime import datetime, timezone, timedelta
from pagewatch.db import get_connection, run_query, run_write
from pagewatch import config


def enqueue_job(url_id, monitor_id=None, job_type="check"):
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()

        if job_type == "picker_snapshot":
            cursor.execute(
                """
                SELECT id FROM jobs
                WHERE monitor_id = ? AND job_type = 'picker_snapshot' AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (monitor_id,)
            )
            if cursor.fetchone():
                conn.commit()
                return None
        else:
            cursor.execute(
                """
                SELECT id FROM jobs
                WHERE url_id = ? AND job_type = 'check' AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (url_id,)
            )
            if cursor.fetchone():
                conn.commit()
                return None

        cursor.execute(
            """
            INSERT INTO jobs (url_id, monitor_id, job_type, status, attempts, run_after, created_at)
            VALUES (?, ?, ?, 'queued', 0, ?, ?)
            """,
            (url_id, monitor_id, job_type, now_iso, now_iso)
        )
        job_id = cursor.lastrowid
        conn.commit()
        return job_id
    finally:
        conn.close()


def claim_next_job():
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM jobs
            WHERE status = 'queued' AND (run_after IS NULL OR run_after <= ?)
            ORDER BY id ASC
            LIMIT 1
            """,
            (now_iso,)
        )
        row = cursor.fetchone()
        if not row:
            conn.commit()
            return None

        job_id = row["id"]
        cursor.execute(
            """
            UPDATE jobs
            SET status = 'running',
                started_at = ?,
                attempts = attempts + 1
            WHERE id = ?
            """,
            (now_iso, job_id)
        )
        conn.commit()

        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        claimed = cursor.fetchone()
        return dict(claimed)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_job(job_id):
    now_iso = datetime.now(timezone.utc).isoformat()
    run_write(
        """
        UPDATE jobs
        SET status = 'done',
            finished_at = ?
        WHERE id = ?
        """,
        (now_iso, job_id)
    )


def fail_job(job_id, error_message):
    rows = run_query("SELECT attempts FROM jobs WHERE id = ?", (job_id,))
    if not rows:
        return

    attempts = rows[0]["attempts"]
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    error_str = str(error_message)[:500]

    if attempts < config.MAX_RETRIES:
        # exponential backoff: 1 min, 2 min, 4 min
        backoff_minutes = 2 ** max(0, attempts - 1)
        retry_time = (now + timedelta(minutes=backoff_minutes)).isoformat()

        run_write(
            """
            UPDATE jobs
            SET status = 'queued',
                run_after = ?,
                error = ?
            WHERE id = ?
            """,
            (retry_time, error_str, job_id)
        )
    else:
        run_write(
            """
            UPDATE jobs
            SET status = 'failed',
                finished_at = ?,
                error = ?
            WHERE id = ?
            """,
            (now_iso, error_str, job_id)
        )


def reset_stuck_jobs(stuck_minutes=5):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE jobs
        SET status = 'queued',
            run_after = ?,
            error = 'Reset after getting stuck in running state'
        WHERE status = 'running' AND started_at <= ?
        """,
        (now_iso, cutoff)
    )
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return count
