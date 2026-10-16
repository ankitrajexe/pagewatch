import os
import random
from datetime import datetime, timezone, timedelta
from pagewatch import config
from pagewatch.db import get_connection, run_query, run_write
from pagewatch.normalizer import (
    extract_text_from_html,
    normalize_text,
    hash_text,
    compare_texts,
    parse_selector_lines,
)
from pagewatch.alerts import notify_change, notify_status
from pagewatch.summary import make_summary


def check_monitor(monitor, fetch_result):
    monitor = dict(monitor)
    monitor_id = monitor["id"]
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    interval_minutes = int(monitor.get("interval_minutes", 60))

    # jitter up to 60s avoids burst requests
    jitter_seconds = random.randint(0, 60)
    next_check_iso = (now + timedelta(minutes=interval_minutes, seconds=jitter_seconds)).isoformat()
    duration_ms = int(fetch_result.get("duration_ms", 0))

    if not fetch_result.get("ok"):
        error_msg = fetch_result.get("error_message") or "fetch failed"
        http_status = fetch_result.get("http_status")
        consecutive_failures = int(monitor.get("consecutive_failures", 0)) + 1

        run_write(
            """
            UPDATE monitors
            SET status = 'error',
                status_message = ?,
                consecutive_failures = ?,
                last_checked_at = ?,
                next_check_at = ?
            WHERE id = ?
            """,
            (error_msg, consecutive_failures, now_iso, next_check_iso, monitor_id)
        )
        run_write(
            """
            INSERT INTO check_log (monitor_id, checked_at, outcome, message, http_status, duration_ms)
            VALUES (?, ?, 'error', ?, ?, ?)
            """,
            (monitor_id, now_iso, error_msg, http_status, duration_ms)
        )

        if consecutive_failures == 3:
            notify_status(monitor, "down", error_msg)

        return {"outcome": "error", "snapshot_id": None, "message": error_msg}

    html = fetch_result.get("html", "")
    include_selectors = monitor.get("include_selectors", "")
    ignore_selectors = monitor.get("ignore_selectors", "")

    extracted_text, _ = extract_text_from_html(
        html,
        include_selectors=include_selectors,
        ignore_selectors=ignore_selectors
    )

    if parse_selector_lines(include_selectors) and not extracted_text.strip():
        error_msg = "Selector matched nothing"
        consecutive_failures = int(monitor.get("consecutive_failures", 0)) + 1

        run_write(
            """
            UPDATE monitors
            SET status = 'error',
                status_message = ?,
                consecutive_failures = ?,
                last_checked_at = ?,
                next_check_at = ?
            WHERE id = ?
            """,
            (error_msg, consecutive_failures, now_iso, next_check_iso, monitor_id)
        )
        run_write(
            """
            INSERT INTO check_log (monitor_id, checked_at, outcome, message, http_status, duration_ms)
            VALUES (?, ?, 'error', ?, ?, ?)
            """,
            (monitor_id, now_iso, error_msg, fetch_result.get("http_status", 200), duration_ms)
        )

        if consecutive_failures == 3:
            notify_status(monitor, "down", error_msg)

        return {"outcome": "error", "snapshot_id": None, "message": error_msg}

    cleaned_text = normalize_text(extracted_text)
    # limit stored text to 1 MB
    if len(cleaned_text.encode("utf-8")) > 1024 * 1024:
        truncated_bytes = cleaned_text.encode("utf-8")[:1024 * 1024]
        cleaned_text = truncated_bytes.decode("utf-8", errors="ignore") + "\n\n[Truncated: page text exceeded 1 MB limit]"

    current_hash = hash_text(cleaned_text)

    previous_snapshots = run_query(
        "SELECT * FROM snapshots WHERE monitor_id = ? ORDER BY id DESC LIMIT 1",
        (monitor_id,)
    )

    if not previous_snapshots:
        snapshot_id = _save_snapshot(
            monitor_id,
            now_iso,
            current_hash,
            cleaned_text,
            fetch_result.get("screenshot_bytes", b""),
            summary="Baseline snapshot created"
        )

        run_write(
            """
            UPDATE monitors
            SET status = 'ok',
                status_message = '',
                consecutive_failures = 0,
                noisy_streak = 0,
                is_noisy = 0,
                last_checked_at = ?,
                last_changed_at = ?,
                next_check_at = ?
            WHERE id = ?
            """,
            (now_iso, now_iso, next_check_iso, monitor_id)
        )
        run_write(
            """
            INSERT INTO check_log (monitor_id, checked_at, outcome, message, http_status, duration_ms)
            VALUES (?, ?, 'changed', 'Baseline snapshot created', ?, ?)
            """,
            (monitor_id, now_iso, fetch_result.get("http_status", 200), duration_ms)
        )

        if int(monitor.get("consecutive_failures", 0)) >= 3:
            notify_status(monitor, "recovered", "Site is back online")

        _handle_number_tracking(monitor, html, snapshot_id, now_iso)
        return {"outcome": "changed", "snapshot_id": snapshot_id, "message": "Baseline snapshot created"}

    prev = previous_snapshots[0]
    prev_hash = prev["content_hash"]

    if current_hash == prev_hash:
        run_write(
            """
            UPDATE monitors
            SET status = 'ok',
                status_message = '',
                consecutive_failures = 0,
                noisy_streak = 0,
                is_noisy = 0,
                last_checked_at = ?,
                next_check_at = ?
            WHERE id = ?
            """,
            (now_iso, next_check_iso, monitor_id)
        )
        run_write(
            """
            INSERT INTO check_log (monitor_id, checked_at, outcome, message, http_status, duration_ms)
            VALUES (?, ?, 'unchanged', 'Content unchanged', ?, ?)
            """,
            (monitor_id, now_iso, fetch_result.get("http_status", 200), duration_ms)
        )

        if int(monitor.get("consecutive_failures", 0)) >= 3:
            notify_status(monitor, "recovered", "Site is back online")

        _handle_number_tracking(monitor, html, None, now_iso)
        return {"outcome": "unchanged", "snapshot_id": None, "message": "Content unchanged"}

    old_text = ""
    if prev["text_path"] and os.path.exists(prev["text_path"]):
        try:
            with open(prev["text_path"], "r", encoding="utf-8") as f:
                old_text = f.read()
        except Exception:
            old_text = ""

    comp = compare_texts(
        old_text,
        cleaned_text,
        sensitivity=monitor.get("sensitivity", "medium")
    )

    if not comp["is_meaningful"]:
        run_write(
            """
            UPDATE monitors
            SET status = 'ok',
                status_message = '',
                consecutive_failures = 0,
                noisy_streak = 0,
                is_noisy = 0,
                last_checked_at = ?,
                next_check_at = ?
            WHERE id = ?
            """,
            (now_iso, next_check_iso, monitor_id)
        )
        run_write(
            """
            INSERT INTO check_log (monitor_id, checked_at, outcome, message, http_status, duration_ms)
            VALUES (?, ?, 'unchanged', 'below sensitivity', ?, ?)
            """,
            (monitor_id, now_iso, fetch_result.get("http_status", 200), duration_ms)
        )

        if int(monitor.get("consecutive_failures", 0)) >= 3:
            notify_status(monitor, "recovered", "Site is back online")

        _handle_number_tracking(monitor, html, None, now_iso)
        return {"outcome": "unchanged", "snapshot_id": None, "message": "below sensitivity"}

    summary = make_summary(old_text, cleaned_text, keyword=monitor.get("keyword"))
    snapshot_id = _save_snapshot(
        monitor_id,
        now_iso,
        current_hash,
        cleaned_text,
        fetch_result.get("screenshot_bytes", b""),
        summary=summary
    )

    noisy_streak = int(monitor.get("noisy_streak", 0)) + 1
    is_noisy = 1 if noisy_streak >= config.NOISY_STREAK_LIMIT else 0
    change_msg = f"Content changed ({comp['changed_line_percent']}% lines)"

    run_write(
        """
        UPDATE monitors
        SET status = 'ok',
            status_message = '',
            consecutive_failures = 0,
            noisy_streak = ?,
            is_noisy = ?,
            last_checked_at = ?,
            last_changed_at = ?,
            next_check_at = ?
        WHERE id = ?
        """,
        (noisy_streak, is_noisy, now_iso, now_iso, next_check_iso, monitor_id)
    )
    run_write(
        """
        INSERT INTO check_log (monitor_id, checked_at, outcome, message, http_status, duration_ms)
        VALUES (?, ?, 'changed', ?, ?, ?)
        """,
        (monitor_id, now_iso, change_msg, fetch_result.get("http_status", 200), duration_ms)
    )

    if int(monitor.get("consecutive_failures", 0)) >= 3:
        notify_status(monitor, "recovered", "Site is back online")

    new_snapshot_rows = run_query("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,))
    if new_snapshot_rows:
        new_snapshot = new_snapshot_rows[0]
        updated_monitor = dict(monitor)
        updated_monitor["noisy_streak"] = noisy_streak
        updated_monitor["is_noisy"] = is_noisy
        notify_change(updated_monitor, prev, new_snapshot, summary)

    _handle_number_tracking(monitor, html, snapshot_id, now_iso)
    return {"outcome": "changed", "snapshot_id": snapshot_id, "message": change_msg}


def _handle_number_tracking(monitor, html, snapshot_id, now_iso):
    selector = (monitor.get("number_selector") or "").strip()
    if not selector:
        return

    try:
        from pagewatch.numbers import (
            extract_number_from_html,
            record_number_point,
            check_and_alert_thresholds,
        )
        val = extract_number_from_html(html, selector)
        if val is not None:
            record_number_point(monitor["id"], snapshot_id, val, now_iso)
            check_and_alert_thresholds(monitor, val, snapshot_id)
    except Exception as err:
        print(f"number tracking failed: {err}")


def _save_snapshot(monitor_id, taken_at, content_hash, text_content, screenshot_bytes, summary=""):
    os.makedirs(config.TEXT_DIR, exist_ok=True)
    os.makedirs(config.SCREENSHOT_DIR, exist_ok=True)

    snapshot_id = run_write(
        """
        INSERT INTO snapshots (
            monitor_id, taken_at, content_hash,
            text_path, screenshot_path, text_length, summary
        ) VALUES (?, ?, ?, '', '', ?, ?)
        """,
        (monitor_id, taken_at, content_hash, len(text_content), summary)
    )

    text_filename = f"{monitor_id}_{snapshot_id}.txt"
    screenshot_filename = f"{monitor_id}_{snapshot_id}.png"
    text_path = os.path.join(config.TEXT_DIR, text_filename)
    screenshot_path = os.path.join(config.SCREENSHOT_DIR, screenshot_filename)

    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text_content)

    if screenshot_bytes:
        with open(screenshot_path, "wb") as f:
            f.write(screenshot_bytes)

    run_write(
        """
        UPDATE snapshots
        SET text_path = ?,
            screenshot_path = ?
        WHERE id = ?
        """,
        (text_path, screenshot_path, snapshot_id)
    )

    return snapshot_id
