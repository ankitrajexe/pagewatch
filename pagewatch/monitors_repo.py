import os
from datetime import datetime, timezone
from pagewatch import config
from pagewatch.db import get_connection, run_query, run_write
from pagewatch.urlutils import normalize_url, get_domain


def get_or_create_url(raw_url):
    clean_url = normalize_url(raw_url)
    domain = get_domain(clean_url)

    rows = run_query("SELECT id FROM urls WHERE url = ?", (clean_url,))
    if rows:
        return rows[0]["id"], clean_url

    new_id = run_write(
        "INSERT INTO urls (url, domain, consecutive_failures) VALUES (?, ?, 0)",
        (clean_url, domain)
    )
    return new_id, clean_url


def create_monitor(data):
    url_id, clean_url = get_or_create_url(data["url"])
    now_iso = datetime.now(timezone.utc).isoformat()

    below_val = float(data["number_alert_below"]) if data.get("number_alert_below") not in (None, "") else None
    above_val = float(data["number_alert_above"]) if data.get("number_alert_above") not in (None, "") else None

    monitor_id = run_write(
        """
        INSERT INTO monitors (
            name, url_id, interval_minutes, sensitivity,
            include_selectors, ignore_selectors, keyword, number_selector,
            number_alert_below, number_alert_above,
            alert_email, telegram_chat_id, discord_webhook_url,
            daily_digest, status, status_message,
            next_check_at, noisy_streak, is_noisy,
            consecutive_failures, is_active, created_at
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, 'pending', '',
            ?, 0, 0,
            0, 1, ?
        )
        """,
        (
            data["name"].strip(),
            url_id,
            int(data["interval_minutes"]),
            data.get("sensitivity", "medium"),
            data.get("include_selectors", "").strip(),
            data.get("ignore_selectors", "").strip(),
            data.get("keyword", "").strip(),
            data.get("number_selector", "").strip(),
            below_val,
            above_val,
            data.get("alert_email", "").strip(),
            data.get("telegram_chat_id", "").strip(),
            data.get("discord_webhook_url", "").strip(),
            1 if data.get("daily_digest") else 0,
            now_iso,
            now_iso,
        )
    )
    return monitor_id


def list_monitors():
    return run_query(
        """
        SELECT monitors.*, urls.url, urls.domain
        FROM monitors
        JOIN urls ON monitors.url_id = urls.id
        WHERE monitors.is_active = 1
        ORDER BY monitors.id DESC
        """
    )


def get_monitor(monitor_id):
    rows = run_query(
        """
        SELECT monitors.*, urls.url, urls.domain
        FROM monitors
        JOIN urls ON monitors.url_id = urls.id
        WHERE monitors.id = ?
        """,
        (monitor_id,)
    )
    return rows[0] if rows else None


def update_monitor(monitor_id, data):
    url_id, clean_url = get_or_create_url(data["url"])
    now_iso = datetime.now(timezone.utc).isoformat()

    below_val = float(data["number_alert_below"]) if data.get("number_alert_below") not in (None, "") else None
    above_val = float(data["number_alert_above"]) if data.get("number_alert_above") not in (None, "") else None

    run_write(
        """
        UPDATE monitors
        SET 
            name = ?,
            url_id = ?,
            interval_minutes = ?,
            sensitivity = ?,
            include_selectors = ?,
            ignore_selectors = ?,
            keyword = ?,
            number_selector = ?,
            number_alert_below = ?,
            number_alert_above = ?,
            alert_email = ?,
            telegram_chat_id = ?,
            discord_webhook_url = ?,
            daily_digest = ?,
            next_check_at = ?
        WHERE id = ?
        """,
        (
            data["name"].strip(),
            url_id,
            int(data["interval_minutes"]),
            data.get("sensitivity", "medium"),
            data.get("include_selectors", "").strip(),
            data.get("ignore_selectors", "").strip(),
            data.get("keyword", "").strip(),
            data.get("number_selector", "").strip(),
            below_val,
            above_val,
            data.get("alert_email", "").strip(),
            data.get("telegram_chat_id", "").strip(),
            data.get("discord_webhook_url", "").strip(),
            1 if data.get("daily_digest") else 0,
            now_iso,
            monitor_id,
        )
    )
    return True


def delete_monitor(monitor_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, text_path, screenshot_path FROM snapshots WHERE monitor_id = ?",
            (monitor_id,)
        )
        snapshots = cursor.fetchall()

        for s in snapshots:
            snap_id = s["id"]
            if s["text_path"] and os.path.isfile(s["text_path"]):
                try:
                    os.remove(s["text_path"])
                except OSError:
                    pass
            if s["screenshot_path"] and os.path.isfile(s["screenshot_path"]):
                try:
                    os.remove(s["screenshot_path"])
                except OSError:
                    pass

            diff_dir = getattr(config, "DIFF_DIR", None)
            if diff_dir and os.path.isdir(diff_dir):
                for fname in os.listdir(diff_dir):
                    if fname.startswith(f"diff_{snap_id}_") or f"_{snap_id}." in fname:
                        try:
                            os.remove(os.path.join(diff_dir, fname))
                        except OSError:
                            pass

        picker_dir = getattr(config, "PICKER_DIR", None)
        if picker_dir and os.path.isdir(picker_dir):
            for fname in (f"monitor_{monitor_id}.png", f"monitor_{monitor_id}.json"):
                fpath = os.path.join(picker_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass

        conn.execute("DELETE FROM jobs WHERE monitor_id = ?", (monitor_id,))
        conn.execute("DELETE FROM alerts WHERE monitor_id = ?", (monitor_id,))
        conn.execute("DELETE FROM number_points WHERE monitor_id = ?", (monitor_id,))
        conn.execute("DELETE FROM check_log WHERE monitor_id = ?", (monitor_id,))
        conn.execute("DELETE FROM snapshots WHERE monitor_id = ?", (monitor_id,))
        conn.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
        conn.commit()
    finally:
        conn.close()
    return True
