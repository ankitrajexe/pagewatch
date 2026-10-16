from datetime import datetime, timezone, timedelta
from pagewatch import config
from pagewatch.db import run_query
from pagewatch.summary import make_summary
from pagewatch.alerts import (
    send_email,
    send_telegram,
    send_discord,
    record_alert,
    _read_snapshot_text,
)


def build_digest_for_monitor(monitor, since=None):
    monitor = dict(monitor)
    monitor_id = monitor["id"]

    if since is None:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    recent_snapshots = run_query(
        """
        SELECT * FROM snapshots
        WHERE monitor_id = ? AND taken_at >= ?
        ORDER BY id ASC
        """,
        (monitor_id, since),
    )

    if not recent_snapshots:
        return None

    change_lines = []
    for s in recent_snapshots:
        s_dict = dict(s)
        prev_rows = run_query(
            """
            SELECT * FROM snapshots
            WHERE monitor_id = ? AND id < ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (monitor_id, s_dict["id"]),
        )

        if not prev_rows:
            change_lines.append(f"- Baseline snapshot captured at {s_dict['taken_at'][:16]}")
        else:
            prev = dict(prev_rows[0])
            old_text = _read_snapshot_text(prev)
            new_text = _read_snapshot_text(s_dict)
            summary = s_dict.get("summary") or make_summary(old_text, new_text, keyword=monitor.get("keyword"))
            diff_link = f"{config.BASE_URL}/monitors/{monitor_id}/compare?a={prev['id']}&b={s_dict['id']}"
            change_lines.append(f"- {s_dict['taken_at'][:16]} UTC: {summary}\n  Compare: {diff_link}")

    if not change_lines:
        return None

    header = f"Daily Digest: {monitor['name']}\nURL: {monitor.get('url', '')}\nChanges in last 24h:\n"
    return header + "\n".join(change_lines)


def send_daily_digests(since=None):
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    monitors = run_query(
        """
        SELECT m.*, u.url
        FROM monitors m
        JOIN urls u ON m.url_id = u.id
        WHERE m.is_active = 1 AND m.daily_digest = 1
        """
    )

    sent_count = 0
    for monitor in monitors:
        monitor_dict = dict(monitor)
        monitor_id = monitor_dict["id"]
        digest_text = build_digest_for_monitor(monitor_dict, since=since)

        if not digest_text:
            continue

        subject = f"PageWatch Daily Digest: {monitor_dict['name']}"
        monitor_sent = False

        email_addr = (monitor_dict.get("alert_email") or "").strip()
        if email_addr:
            dedupe_key = f"{monitor_id}:digest:{today_str}:email"
            if record_alert(monitor_id, None, "email", dedupe_key, "Daily digest"):
                if send_email(email_addr, subject, digest_text):
                    monitor_sent = True

        telegram_id = (monitor_dict.get("telegram_chat_id") or "").strip()
        if telegram_id:
            dedupe_key = f"{monitor_id}:digest:{today_str}:telegram"
            if record_alert(monitor_id, None, "telegram", dedupe_key, "Daily digest"):
                if send_telegram(telegram_id, digest_text):
                    monitor_sent = True

        discord_url = (monitor_dict.get("discord_webhook_url") or "").strip()
        if discord_url:
            dedupe_key = f"{monitor_id}:digest:{today_str}:discord"
            if record_alert(monitor_id, None, "discord", dedupe_key, "Daily digest"):
                if send_discord(discord_url, digest_text):
                    monitor_sent = True

        if monitor_sent:
            sent_count += 1

    return sent_count
