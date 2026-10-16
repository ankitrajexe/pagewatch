# tests/test_alerts.py
# --------------------
# What it does: Unit and integration tests for alert channels (email, Telegram, Discord),
#               deduplication, noisy guards, keyword rules, downtime/recovery alerts,
#               and daily digest delivery.
# Talks to: pagewatch/alerts.py, pagewatch/digest.py, pagewatch/checker.py, pagewatch/db.py.

import os
from unittest.mock import MagicMock, patch
import pytest

from pagewatch import config, init
from pagewatch.db import create_tables, run_query, run_write
from pagewatch.monitors_repo import create_monitor, get_monitor
from pagewatch.alerts import (
    send_email,
    send_telegram,
    send_discord,
    record_alert,
    notify_change,
    notify_status,
    send_test_alert,
)
from pagewatch.digest import build_digest_for_monitor, send_daily_digests
from pagewatch.checker import check_monitor


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """
    Set up isolated database and data directories for each test.
    """
    db_file = str(tmp_path / "alerts_test.db")
    texts_dir = str(tmp_path / "texts")
    shots_dir = str(tmp_path / "screenshots")

    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr("pagewatch.db.DB_PATH", db_file)
    monkeypatch.setattr(config, "TEXT_DIR", texts_dir)
    monkeypatch.setattr(config, "SCREENSHOT_DIR", shots_dir)
    monkeypatch.setattr(config, "ALLOW_LOCALHOST", True)
    monkeypatch.setattr(config, "DEV_FAST_MODE", True)

    os.makedirs(texts_dir, exist_ok=True)
    os.makedirs(shots_dir, exist_ok=True)
    create_tables()


# ---------------------------------------------------------------------------
# 1. Low-level sender tests (Email, Telegram, Discord)
# ---------------------------------------------------------------------------

class TestLowLevelSenders:
    def test_send_email_unconfigured_returns_false(self, monkeypatch):
        monkeypatch.setattr(config, "SMTP_HOST", "")
        monkeypatch.setattr(config, "SMTP_FROM", "")
        result = send_email("test@example.com", "Subject", "Body")
        assert result is False

    @patch("smtplib.SMTP")
    def test_send_email_configured_success(self, mock_smtp_class, monkeypatch):
        monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(config, "SMTP_PORT", 587)
        monkeypatch.setattr(config, "SMTP_FROM", "alerts@example.com")
        monkeypatch.setattr(config, "SMTP_USER", "user")
        monkeypatch.setattr(config, "SMTP_PASSWORD", "secret")

        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        result = send_email("recipient@example.com", "Test Subject", "Test Body")
        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user", "secret")
        mock_server.send_message.assert_called_once()

    @patch("smtplib.SMTP")
    def test_send_email_exception_handled_gracefully(self, mock_smtp_class, monkeypatch):
        monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(config, "SMTP_FROM", "alerts@example.com")
        mock_smtp_class.side_effect = Exception("SMTP connection timed out")

        result = send_email("recipient@example.com", "Subject", "Body")
        assert result is False

    def test_send_telegram_unconfigured_returns_false(self, monkeypatch):
        monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
        result = send_telegram("12345", "Test text")
        assert result is False

    @patch("requests.post")
    def test_send_telegram_configured_success(self, mock_post, monkeypatch):
        monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "fake_bot_token")
        mock_res = MagicMock()
        mock_res.raise_for_status.return_value = None
        mock_post.return_value = mock_res

        result = send_telegram("12345678", "Hello Telegram")
        assert result is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "api.telegram.org/botfake_bot_token/sendMessage" in args[0]
        assert kwargs["json"]["chat_id"] == "12345678"
        assert kwargs["json"]["text"] == "Hello Telegram"

    @patch("requests.post")
    def test_send_telegram_exception_handled_gracefully(self, mock_post, monkeypatch):
        monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "fake_bot_token")
        mock_post.side_effect = Exception("Connection error")

        result = send_telegram("12345678", "Hello Telegram")
        assert result is False

    def test_send_discord_empty_url_returns_false(self):
        result = send_discord("", "Test message")
        assert result is False

    @patch("requests.post")
    def test_send_discord_configured_success(self, mock_post):
        mock_res = MagicMock()
        mock_res.raise_for_status.return_value = None
        mock_post.return_value = mock_res

        webhook = "https://discord.com/api/webhooks/123/abc"
        result = send_discord(webhook, "Hello Discord")
        assert result is True
        mock_post.assert_called_once_with(webhook, json={"content": "Hello Discord"}, timeout=10)

    @patch("requests.post")
    def test_send_discord_exception_handled_gracefully(self, mock_post):
        mock_post.side_effect = Exception("Discord API error")
        result = send_discord("https://discord.com/api/webhooks/123/abc", "Hello Discord")
        assert result is False


# ---------------------------------------------------------------------------
# 2. Deduplication tests
# ---------------------------------------------------------------------------

class TestAlertDeduplication:
    def test_record_alert_prevents_duplicate_dedupe_keys(self):
        mid = create_monitor({
            "name": "Dedupe Test",
            "url": "http://127.0.0.1:5001/",
            "interval_minutes": 15,
        })

        # Insert a real snapshot to satisfy foreign key constraints
        sid = run_write(
            """
            INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path)
            VALUES (?, '2026-10-16T10:00:00Z', 'hash', '', '')
            """,
            (mid,)
        )

        dedupe_key = f"{mid}:{sid}:email"
        # First attempt should succeed
        assert record_alert(mid, sid, "email", dedupe_key, "First summary") is True

        # Second attempt with the exact same dedupe_key must return False
        assert record_alert(mid, sid, "email", dedupe_key, "Second summary") is False

        # Different channel for the same snapshot must succeed
        telegram_key = f"{mid}:{sid}:telegram"
        assert record_alert(mid, sid, "telegram", telegram_key, "Telegram summary") is True


# ---------------------------------------------------------------------------
# 3. High-level change notification rules (notify_change)
# ---------------------------------------------------------------------------

class TestNotifyChange:
    @pytest.fixture
    def setup_monitor_and_snapshots(self, tmp_path):
        mid = create_monitor({
            "name": "Shop Monitor",
            "url": "http://127.0.0.1:5001/shop",
            "interval_minutes": 15,
            "alert_email": "alerts@shop.com",
            "telegram_chat_id": "998877",
            "discord_webhook_url": "https://discord.com/api/webhooks/1/2",
        })
        m = get_monitor(mid)

        # Write two snapshot text files
        old_txt = tmp_path / "texts" / "old.txt"
        new_txt = tmp_path / "texts" / "new.txt"
        old_txt.write_text("Old product catalog\nPrice: 100", encoding="utf-8")
        new_txt.write_text("New product catalog\nPrice: 90", encoding="utf-8")

        s1_id = run_write(
            "INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path) VALUES (?, ?, ?, ?, ?)",
            (mid, "2026-10-16T10:00:00Z", "hash1", str(old_txt), "")
        )
        s2_id = run_write(
            "INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path) VALUES (?, ?, ?, ?, ?)",
            (mid, "2026-10-16T11:00:00Z", "hash2", str(new_txt), "")
        )

        s1 = run_query("SELECT * FROM snapshots WHERE id = ?", (s1_id,))[0]
        s2 = run_query("SELECT * FROM snapshots WHERE id = ?", (s2_id,))[0]

        return m, s1, s2

    @patch("pagewatch.alerts.send_email", return_value=True)
    @patch("pagewatch.alerts.send_telegram", return_value=True)
    @patch("pagewatch.alerts.send_discord", return_value=True)
    def test_notify_change_sends_to_all_configured_channels(
        self, mock_discord, mock_telegram, mock_email, setup_monitor_and_snapshots
    ):
        m, s1, s2 = setup_monitor_and_snapshots

        sent = notify_change(m, s1, s2, "Number changed from 100 to 90")
        assert sent is True
        mock_email.assert_called_once()
        mock_telegram.assert_called_once()
        mock_discord.assert_called_once()

        # Database must have 3 recorded alerts
        alert_rows = run_query("SELECT * FROM alerts WHERE monitor_id = ?", (m["id"],))
        assert len(alert_rows) == 3

    @patch("pagewatch.alerts.send_email", return_value=True)
    def test_notify_change_dedupe_prevents_duplicate_sending(
        self, mock_email, setup_monitor_and_snapshots
    ):
        m, s1, s2 = setup_monitor_and_snapshots

        # First alert call
        notify_change(m, s1, s2, "Summary 1")
        assert mock_email.call_count == 1

        # Second alert call with identical snapshots
        notify_change(m, s1, s2, "Summary 2")
        # Email should NOT be called again
        assert mock_email.call_count == 1

    def test_notify_change_baseline_skipped(self, setup_monitor_and_snapshots):
        m, _, s2 = setup_monitor_and_snapshots
        # old_snapshot=None indicates baseline
        assert notify_change(m, None, s2, "Baseline") is False

    @patch("pagewatch.alerts.send_email")
    def test_notify_change_noisy_monitor_skipped(
        self, mock_email, setup_monitor_and_snapshots
    ):
        m, s1, s2 = setup_monitor_and_snapshots
        noisy_monitor = dict(m)
        noisy_monitor["is_noisy"] = 1

        result = notify_change(noisy_monitor, s1, s2, "Change on noisy monitor")
        assert result is False
        mock_email.assert_not_called()

    @patch("pagewatch.alerts.send_email")
    def test_notify_change_daily_digest_skips_instant_alert(
        self, mock_email, setup_monitor_and_snapshots
    ):
        m, s1, s2 = setup_monitor_and_snapshots
        digest_monitor = dict(m)
        digest_monitor["daily_digest"] = 1

        result = notify_change(digest_monitor, s1, s2, "Change")
        assert result is False
        mock_email.assert_not_called()

    @patch("pagewatch.alerts.send_email", return_value=True)
    def test_notify_change_keyword_rules(
        self, mock_email, tmp_path
    ):
        mid = create_monitor({
            "name": "Sale Watcher",
            "url": "http://127.0.0.1:5001/promo",
            "interval_minutes": 15,
            "keyword": "FLASH SALE",
            "alert_email": "user@example.com",
        })
        m = get_monitor(mid)

        f_no_kw = tmp_path / "texts" / "no_kw.txt"
        f_with_kw = tmp_path / "texts" / "with_kw.txt"
        f_with_kw_2 = tmp_path / "texts" / "with_kw_2.txt"

        f_no_kw.write_text("Regular catalog. Nothing special.", encoding="utf-8")
        f_with_kw.write_text("Notice: Flash Sale is now live!", encoding="utf-8")
        f_with_kw_2.write_text("Notice: Flash Sale has 2 hours remaining!", encoding="utf-8")

        s1_id = run_write(
            "INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path) VALUES (?, ?, 'h1', ?, '')",
            (mid, "2026-10-16T10:00:00Z", str(f_no_kw))
        )
        s2_id = run_write(
            "INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path) VALUES (?, ?, 'h2', ?, '')",
            (mid, "2026-10-16T11:00:00Z", str(f_with_kw))
        )
        s3_id = run_write(
            "INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path) VALUES (?, ?, 'h3', ?, '')",
            (mid, "2026-10-16T12:00:00Z", str(f_with_kw_2))
        )
        s4_id = run_write(
            "INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path) VALUES (?, ?, 'h4', ?, '')",
            (mid, "2026-10-16T13:00:00Z", str(f_no_kw))
        )

        s_no = run_query("SELECT * FROM snapshots WHERE id = ?", (s1_id,))[0]
        s_kw1 = run_query("SELECT * FROM snapshots WHERE id = ?", (s2_id,))[0]
        s_kw2 = run_query("SELECT * FROM snapshots WHERE id = ?", (s3_id,))[0]
        s_no_again = run_query("SELECT * FROM snapshots WHERE id = ?", (s4_id,))[0]

        # 1. Keyword appeared: no_kw -> with_kw -> ALERT
        res1 = notify_change(m, s_no, s_kw1, "Keyword appeared")
        assert res1 is True
        assert mock_email.call_count == 1

        # 2. Content changed but keyword was present in both: with_kw -> with_kw_2 -> SUPPRESS
        res2 = notify_change(m, s_kw1, s_kw2, "Content changed while sale active")
        assert res2 is False
        assert mock_email.call_count == 1

        # 3. Keyword disappeared: with_kw_2 -> no_kw -> ALERT
        res3 = notify_change(m, s_kw2, s_no_again, "Keyword disappeared")
        assert res3 is True
        assert mock_email.call_count == 2


# ---------------------------------------------------------------------------
# 4. Downtime and recovery status alerts (notify_status)
# ---------------------------------------------------------------------------

class TestStatusAlerts:
    @patch("pagewatch.alerts.send_email", return_value=True)
    def test_status_alert_down_and_recovery(self, mock_email):
        mid = create_monitor({
            "name": "Uptime Watcher",
            "url": "http://127.0.0.1:5001/status",
            "interval_minutes": 15,
            "alert_email": "admin@example.com",
        })
        m = get_monitor(mid)

        # Trigger downtime alert
        sent_down = notify_status(m, "down", "HTTP 500 Server Error")
        assert sent_down is True
        assert mock_email.call_count == 1
        subject = mock_email.call_args[0][1]
        assert "is DOWN" in subject

        # Further failure checks during the same outage must NOT spam
        sent_down_dup = notify_status(m, "down", "HTTP 500 Server Error")
        assert sent_down_dup is False
        assert mock_email.call_count == 1

        # Recovery alert
        sent_rec = notify_status(m, "recovered", "Site is back online")
        assert sent_rec is True
        assert mock_email.call_count == 2
        rec_subject = mock_email.call_args[0][1]
        assert "recovered" in rec_subject


# ---------------------------------------------------------------------------
# 5. Checker integration with alerts
# ---------------------------------------------------------------------------

class TestCheckerAlertIntegration:
    @patch("pagewatch.checker.notify_change")
    @patch("pagewatch.checker.notify_status")
    def test_checker_triggers_notify_change_on_meaningful_change(
        self, mock_status, mock_change
    ):
        mid = create_monitor({
            "name": "Integration Shop",
            "url": "http://127.0.0.1:5001/int",
            "interval_minutes": 15,
            "sensitivity": "high",
        })
        m = get_monitor(mid)

        # 1st check: baseline
        fetch1 = {
            "ok": True,
            "http_status": 200,
            "final_url": "http://127.0.0.1:5001/int",
            "html": "<html><body><p>Hello V1</p></body></html>",
            "page_text": "Hello V1",
            "screenshot_bytes": b"fake",
            "duration_ms": 100,
        }
        check_monitor(m, fetch1)
        mock_change.assert_not_called()

        # 2nd check: identical -> no alert
        m_refreshed = get_monitor(mid)
        check_monitor(m_refreshed, fetch1)
        mock_change.assert_not_called()

        # 3rd check: changed -> notify_change must be called
        fetch2 = dict(fetch1, html="<html><body><p>Hello V2 Changed</p></body></html>")
        check_monitor(m_refreshed, fetch2)
        mock_change.assert_called_once()

    @patch("pagewatch.checker.notify_status")
    def test_checker_triggers_down_status_on_third_consecutive_failure(self, mock_status):
        mid = create_monitor({
            "name": "Failing Target",
            "url": "http://127.0.0.1:5001/fail",
            "interval_minutes": 15,
        })
        m = get_monitor(mid)

        fail_fetch = {
            "ok": False,
            "http_status": 500,
            "final_url": "http://127.0.0.1:5001/fail",
            "html": "",
            "page_text": "",
            "screenshot_bytes": b"",
            "error_type": "http",
            "error_message": "Internal Server Error",
            "duration_ms": 50,
        }

        # Failure 1
        check_monitor(m, fail_fetch)
        mock_status.assert_not_called()

        # Failure 2
        m = get_monitor(mid)
        check_monitor(m, fail_fetch)
        mock_status.assert_not_called()

        # Failure 3 -> should trigger notify_status("down")
        m = get_monitor(mid)
        check_monitor(m, fail_fetch)
        mock_status.assert_called_once()
        assert mock_status.call_args[0][1] == "down"


# ---------------------------------------------------------------------------
# 6. Test Alert and Daily Digest
# ---------------------------------------------------------------------------

class TestTestAlertAndDigest:
    @patch("pagewatch.alerts.send_email", return_value=True)
    @patch("pagewatch.alerts.send_telegram", return_value=True)
    @patch("pagewatch.alerts.send_discord", return_value=True)
    def test_send_test_alert(self, mock_discord, mock_telegram, mock_email):
        mid = create_monitor({
            "name": "Manual Test",
            "url": "http://127.0.0.1:5001/",
            "interval_minutes": 15,
            "alert_email": "test@example.com",
            "telegram_chat_id": "111",
            "discord_webhook_url": "https://discord.com/webhook",
        })
        m = get_monitor(mid)

        res = send_test_alert(m)
        assert res.get("email") is True
        assert res.get("telegram") is True
        assert res.get("discord") is True
        mock_email.assert_called_once()
        mock_telegram.assert_called_once()
        mock_discord.assert_called_once()

    @patch("pagewatch.digest.send_email", return_value=True)
    def test_send_daily_digests(self, mock_email, tmp_path):
        mid = create_monitor({
            "name": "Daily Digest Target",
            "url": "http://127.0.0.1:5001/digest",
            "interval_minutes": 60,
            "daily_digest": 1,
            "alert_email": "digest@example.com",
        })
        m = get_monitor(mid)

        # Add snapshots
        t1 = tmp_path / "texts" / "t1.txt"
        t2 = tmp_path / "texts" / "t2.txt"
        t1.write_text("Headline 1", encoding="utf-8")
        t2.write_text("Headline 2", encoding="utf-8")

        run_write(
            "INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path) VALUES (?, ?, ?, ?, ?)",
            (mid, "2026-10-16T08:00:00Z", "h1", str(t1), "")
        )
        run_write(
            "INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path) VALUES (?, ?, ?, ?, ?)",
            (mid, "2026-10-16T12:00:00Z", "h2", str(t2), "")
        )

        digest = build_digest_for_monitor(m, since="2026-10-16T00:00:00Z")
        assert digest is not None
        assert "Daily Digest: Daily Digest Target" in digest

        count = send_daily_digests(since="2026-10-16T00:00:00Z")
        assert count == 1
        mock_email.assert_called_once()


# ---------------------------------------------------------------------------
# 7. Web Routes tests (/monitors/<id>/test-alert and /admin/send-digest-now)
# ---------------------------------------------------------------------------

class TestAlertWebRoutes:
    @pytest.fixture
    def app(self):
        flask_app = init(start_worker=False, start_scheduler_thread=False)
        flask_app.config["TESTING"] = True
        return flask_app

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    @patch("pagewatch.alerts.send_test_alert", return_value={"email": True})
    def test_post_test_alert_route(self, mock_send, client):
        mid = create_monitor({
            "name": "Route Test Monitor",
            "url": "http://127.0.0.1:5001/",
            "interval_minutes": 15,
            "alert_email": "route@example.com",
        })

        resp = client.post(f"/monitors/{mid}/test-alert", follow_redirects=True)
        assert resp.status_code == 200
        mock_send.assert_called_once()
        assert b"Test alert sent to" in resp.data

    @patch("pagewatch.digest.send_daily_digests", return_value=2)
    def test_post_admin_send_digest_now_route(self, mock_digest, client):
        resp = client.post("/admin/send-digest-now", follow_redirects=True)
        assert resp.status_code == 200
        mock_digest.assert_called_once()
        assert b"Daily digest executed for 2 monitor(s)" in resp.data
