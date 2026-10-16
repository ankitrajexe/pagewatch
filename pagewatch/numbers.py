import io
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from pagewatch import config
from pagewatch.db import run_query, run_write
from pagewatch.alerts import send_email, send_telegram, send_discord, record_alert


def parse_number(text):
    if not text or not isinstance(text, str):
        return None

    matches = re.finditer(r"[-+]?\s*\d+(?:[.,\s]\d+)*(?:[.,]\d+)?", text)
    for m in matches:
        val = _convert_to_float(m.group(0).strip())
        if val is not None:
            return val
    return None


def _convert_to_float(s):
    if not s:
        return None

    s = s.replace(" ", "")
    is_negative = s.startswith("-")
    if s.startswith("-") or s.startswith("+"):
        s = s[1:]

    if not any(c.isdigit() for c in s):
        return None

    if "," in s and "." in s:
        last_comma = s.rfind(",")
        last_dot = s.rfind(".")
        if last_comma > last_dot:
            # european format: 1.234,50
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if s.count(",") > 1:
            s = s.replace(",", "")
        else:
            parts = s.split(",")
            if len(parts[1]) == 3:
                s = s.replace(",", "")
            else:
                s = s.replace(",", ".")
    elif "." in s and s.count(".") > 1:
        s = s.replace(".", "")

    try:
        val = float(s)
        return -val if is_negative else val
    except ValueError:
        return None


def extract_number_from_html(html, number_selector):
    if not html or not number_selector:
        return None
    try:
        soup = BeautifulSoup(html, "lxml")
        element = soup.select_one(number_selector)
        if element:
            return parse_number(element.get_text())
    except Exception as err:
        print(f"number extract failed: {err}")
    return None


def record_number_point(monitor_id, snapshot_id, value, taken_at=None):
    if taken_at is None:
        taken_at = datetime.now(timezone.utc).isoformat()
    return run_write(
        """
        INSERT INTO number_points (monitor_id, snapshot_id, value, taken_at)
        VALUES (?, ?, ?, ?)
        """,
        (monitor_id, snapshot_id, float(value), taken_at)
    )


def check_and_alert_thresholds(monitor, value, snapshot_id=None):
    monitor = dict(monitor)
    monitor_id = monitor["id"]
    name = monitor.get("name", f"Monitor #{monitor_id}")
    url = monitor.get("url", "")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    alert_below = monitor.get("number_alert_below")
    alert_above = monitor.get("number_alert_above")

    condition = None
    reason = None

    if alert_below is not None and value < float(alert_below):
        condition = "below"
        reason = f"Value {value} dropped below threshold {alert_below}"
    elif alert_above is not None and value > float(alert_above):
        condition = "above"
        reason = f"Value {value} rose above threshold {alert_above}"

    if not condition:
        return False

    subject = f"PageWatch Threshold Alert: {name}"
    message = (
        f"PageWatch Number Threshold Alert: {name}\n"
        f"URL: {url}\n"
        f"Current Value: {value}\n"
        f"Alert: {reason}\n"
        f"Time: {now_str}\n"
        f"Monitor Dashboard: {config.BASE_URL}/monitors/{monitor_id}"
    )

    sent_any = False

    email_addr = (monitor.get("alert_email") or "").strip()
    if email_addr:
        dedupe_key = f"{monitor_id}:thresh_{condition}:{value}:email"
        if record_alert(monitor_id, snapshot_id, "email", dedupe_key, reason):
            send_email(email_addr, subject, message)
            sent_any = True

    telegram_id = (monitor.get("telegram_chat_id") or "").strip()
    if telegram_id:
        dedupe_key = f"{monitor_id}:thresh_{condition}:{value}:telegram"
        if record_alert(monitor_id, snapshot_id, "telegram", dedupe_key, reason):
            send_telegram(telegram_id, message)
            sent_any = True

    discord_url = (monitor.get("discord_webhook_url") or "").strip()
    if discord_url:
        dedupe_key = f"{monitor_id}:thresh_{condition}:{value}:discord"
        if record_alert(monitor_id, snapshot_id, "discord", dedupe_key, reason):
            send_discord(discord_url, message)
            sent_any = True

    return sent_any


def generate_number_chart(monitor):
    monitor = dict(monitor)
    monitor_id = monitor["id"]
    name = monitor.get("name", f"Monitor #{monitor_id}")

    rows = run_query(
        """
        SELECT value, taken_at
        FROM (
            SELECT value, taken_at
            FROM number_points
            WHERE monitor_id = ?
            ORDER BY id DESC
            LIMIT 200
        )
        ORDER BY taken_at ASC
        """,
        (monitor_id,)
    )

    fig, ax = plt.subplots(figsize=(8, 3.5), dpi=100)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    if not rows:
        ax.text(
            0.5, 0.5, "No numeric points recorded yet.\nRun checks to track values.",
            horizontalalignment="center", verticalalignment="center",
            transform=ax.transAxes, color="#7f8c8d", fontsize=11
        )
        ax.set_title(f"{name} — Number Tracking", fontsize=12, fontweight="bold", pad=12)
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        dates = []
        values = []
        for r in rows:
            try:
                dates.append(datetime.fromisoformat(r["taken_at"]))
                values.append(float(r["value"]))
            except Exception:
                continue

        ax.plot(dates, values, color="#2980b9", marker="o", markersize=4, linewidth=2, label="Value")

        alert_below = monitor.get("number_alert_below")
        alert_above = monitor.get("number_alert_above")

        if alert_below is not None:
            ax.axhline(float(alert_below), color="#e74c3c", linestyle="--", linewidth=1.5, label=f"Alert Below ({alert_below})")

        if alert_above is not None:
            ax.axhline(float(alert_above), color="#e67e22", linestyle="--", linewidth=1.5, label=f"Alert Above ({alert_above})")

        ax.set_title(f"{name} — Value Over Time", fontsize=12, fontweight="bold", pad=12)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d %H:%M"))
        fig.autofmt_xdate(rotation=30, ha="right")
        ax.grid(True, linestyle=":", alpha=0.6, color="#bdc3c7")
        ax.legend(loc="best", fontsize=9)

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
