import os
import sqlite3
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone
import requests

from pagewatch import config
from pagewatch.db import get_connection, run_query


def send_email(to_email, subject, body):
    if not config.SMTP_HOST or not config.SMTP_FROM or not to_email:
        print("email skipped (not configured)")
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = config.SMTP_FROM
        msg["To"] = to_email
        msg.set_content(body)

        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
            server.starttls()
            if config.SMTP_USER and config.SMTP_PASSWORD:
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as err:
        print(f"email failed: {err}")
        return False


def send_telegram(chat_id, text):
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        print("telegram skipped (not configured)")
        return False

    api_url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }

    try:
        res = requests.post(api_url, json=payload, timeout=10)
        res.raise_for_status()
        return True
    except Exception as err:
        print(f"telegram failed: {err}")
        return False


def send_discord(webhook_url, text):
    if not webhook_url:
        print("discord skipped (not configured)")
        return False

    payload = {"content": text}
    try:
        res = requests.post(webhook_url, json=payload, timeout=10)
        res.raise_for_status()
        return True
    except Exception as err:
        print(f"discord failed: {err}")
        return False


def record_alert(monitor_id, snapshot_id, channel, dedupe_key, summary=""):
    conn = get_connection()
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO alerts (monitor_id, snapshot_id, channel, dedupe_key, summary, sent_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (monitor_id, snapshot_id, channel, dedupe_key, summary, now_iso),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # duplicate alert, skip silently
        return False
    except Exception as err:
        print(f"alert record failed: {err}")
        return False
    finally:
        conn.close()


def notify_change(monitor, old_snapshot, new_snapshot, summary):
    if not old_snapshot or not new_snapshot:
        return False

    monitor = dict(monitor)
    monitor_id = monitor["id"]

    if int(monitor.get("is_noisy", 0)) == 1:
        return False

    if int(monitor.get("daily_digest", 0)) == 1:
        return False

    keyword = (monitor.get("keyword") or "").strip().lower()
    if keyword:
        old_text = _read_snapshot_text(old_snapshot)
        new_text = _read_snapshot_text(new_snapshot)
        was_present = keyword in old_text.lower()
        is_present = keyword in new_text.lower()
        if was_present == is_present:
            return False

    name = monitor.get("name", f"Monitor #{monitor_id}")
    url = monitor.get("url", "")
    old_id = old_snapshot["id"] if isinstance(old_snapshot, dict) else old_snapshot["id"]
    new_id = new_snapshot["id"] if isinstance(new_snapshot, dict) else new_snapshot["id"]

    diff_link = f"{config.BASE_URL}/monitors/{monitor_id}/compare?a={old_id}&b={new_id}"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    subject = f"PageWatch Alert: {name} changed"
    message = (
        f"PageWatch Change Detected: {name}\n"
        f"URL: {url}\n"
        f"Summary: {summary}\n"
        f"Time: {now_str}\n"
        f"Compare diff: {diff_link}"
    )

    sent_any = False

    email_addr = (monitor.get("alert_email") or "").strip()
    if email_addr:
        dedupe_key = f"{monitor_id}:{new_id}:email"
        if record_alert(monitor_id, new_id, "email", dedupe_key, summary):
            send_email(email_addr, subject, message)
            sent_any = True

    telegram_id = (monitor.get("telegram_chat_id") or "").strip()
    if telegram_id:
        dedupe_key = f"{monitor_id}:{new_id}:telegram"
        if record_alert(monitor_id, new_id, "telegram", dedupe_key, summary):
            send_telegram(telegram_id, message)
            sent_any = True

    discord_url = (monitor.get("discord_webhook_url") or "").strip()
    if discord_url:
        dedupe_key = f"{monitor_id}:{new_id}:discord"
        if record_alert(monitor_id, new_id, "discord", dedupe_key, summary):
            send_discord(discord_url, message)
            sent_any = True

    return sent_any


def notify_status(monitor, kind, message):
    monitor = dict(monitor)
    monitor_id = monitor["id"]
    name = monitor.get("name", f"Monitor #{monitor_id}")
    url = monitor.get("url", "")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    episode_marker = _get_failure_episode_marker(monitor_id)

    if kind in ("down", "blocked"):
        subject = f"PageWatch Alert: {name} is {kind.upper()}"
        text = (
            f"PageWatch Alert: {name} is {kind.upper()}\n"
            f"URL: {url}\n"
            f"Reason: {message}\n"
            f"Time: {now_str}\n"
            f"Dashboard: {config.BASE_URL}/"
        )
    else:
        subject = f"PageWatch Resolved: {name} has recovered"
        text = (
            f"PageWatch Resolved: {name} is back online\n"
            f"URL: {url}\n"
            f"Details: {message}\n"
            f"Time: {now_str}\n"
            f"Dashboard: {config.BASE_URL}/"
        )

    sent_any = False

    email_addr = (monitor.get("alert_email") or "").strip()
    if email_addr:
        dedupe_key = f"{monitor_id}:{kind}:{episode_marker}:email"
        if record_alert(monitor_id, None, "email", dedupe_key, message):
            send_email(email_addr, subject, text)
            sent_any = True

    telegram_id = (monitor.get("telegram_chat_id") or "").strip()
    if telegram_id:
        dedupe_key = f"{monitor_id}:{kind}:{episode_marker}:telegram"
        if record_alert(monitor_id, None, "telegram", dedupe_key, message):
            send_telegram(telegram_id, text)
            sent_any = True

    discord_url = (monitor.get("discord_webhook_url") or "").strip()
    if discord_url:
        dedupe_key = f"{monitor_id}:{kind}:{episode_marker}:discord"
        if record_alert(monitor_id, None, "discord", dedupe_key, message):
            send_discord(discord_url, text)
            sent_any = True

    return sent_any


def send_test_alert(monitor):
    monitor = dict(monitor)
    name = monitor.get("name", "Test Monitor")
    url = monitor.get("url", "")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    subject = f"PageWatch Test Alert: {name}"
    text = (
        f"PageWatch Test Notification\n"
        f"Monitor: {name}\n"
        f"URL: {url}\n"
        f"Time: {now_str}\n"
        f"Your alert channels are configured and working properly."
    )

    results = {}
    email_addr = (monitor.get("alert_email") or "").strip()
    if email_addr:
        results["email"] = send_email(email_addr, subject, text)

    telegram_id = (monitor.get("telegram_chat_id") or "").strip()
    if telegram_id:
        results["telegram"] = send_telegram(telegram_id, text)

    discord_url = (monitor.get("discord_webhook_url") or "").strip()
    if discord_url:
        results["discord"] = send_discord(discord_url, text)

    return results


def _read_snapshot_text(snapshot):
    if not snapshot:
        return ""
    path = snapshot.get("text_path") if isinstance(snapshot, dict) else snapshot["text_path"]
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""
    return ""


def _get_failure_episode_marker(monitor_id):
    try:
        rows = run_query(
            """
            SELECT checked_at
            FROM check_log
            WHERE monitor_id = ? AND outcome IN ('changed', 'unchanged')
            ORDER BY id DESC
            LIMIT 1
            """,
            (monitor_id,),
        )
        if rows and rows[0]["checked_at"]:
            return rows[0]["checked_at"]
    except Exception:
        pass
    return "initial"
