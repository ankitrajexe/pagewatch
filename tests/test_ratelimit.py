# tests/test_ratelimit.py
# -----------------------
# What it does: Unit tests for rate limiting (wait_for_domain), robots.txt
#               parsing/checking, and HTTP backoff calculations.
# Talks to: pagewatch/ratelimit.py, pagewatch/config.py, pagewatch/db.py

import time
import pytest
from datetime import datetime, timezone, timedelta
from pagewatch import config
from pagewatch.db import create_tables, run_write, run_query
from pagewatch.ratelimit import (
    wait_for_domain,
    parse_robots_txt,
    is_allowed_by_robots,
    apply_backoff,
    _LAST_FETCH_TIMES,
    _ROBOTS_CACHE,
)


@pytest.fixture(autouse=True)
def setup_ratelimit_env(tmp_path, monkeypatch):
    """Clean in-memory rate limit structures and setup test database."""
    _LAST_FETCH_TIMES.clear()
    _ROBOTS_CACHE.clear()

    test_db = str(tmp_path / "ratelimit_test.db")
    monkeypatch.setattr(config, "DB_PATH", test_db)
    monkeypatch.setattr("pagewatch.db.DB_PATH", test_db)
    create_tables()


class TestWaitForDomain:
    """Tests for wait_for_domain rate limiting."""

    def test_first_fetch_to_domain_does_not_sleep(self, monkeypatch):
        """First fetch to a domain should not need to sleep."""
        sleep_calls = []
        monkeypatch.setattr("pagewatch.ratelimit.time.sleep", lambda s: sleep_calls.append(s))
        monkeypatch.setattr(config, "DOMAIN_DELAY_SECONDS", 10)

        wait_for_domain("newdomain.com")

        assert len(sleep_calls) == 0
        assert "newdomain.com" in _LAST_FETCH_TIMES

    def test_consecutive_fetch_within_delay_sleeps(self, monkeypatch):
        """Fetching the same domain too soon sleeps for the remaining delay."""
        current_time = [1000.0]

        def fake_time():
            return current_time[0]

        sleep_calls = []

        def fake_sleep(duration):
            sleep_calls.append(duration)
            current_time[0] += duration

        monkeypatch.setattr("pagewatch.ratelimit.time.time", fake_time)
        monkeypatch.setattr("pagewatch.ratelimit.time.sleep", fake_sleep)
        monkeypatch.setattr(config, "DOMAIN_DELAY_SECONDS", 10)

        # First fetch at t=1000.0
        wait_for_domain("example.com")
        assert len(sleep_calls) == 0

        # Advance clock by 3 seconds (t=1003.0)
        current_time[0] = 1003.0

        # Second fetch needs 7 seconds more
        wait_for_domain("example.com")
        total_slept = sum(sleep_calls)
        assert round(total_slept, 1) == 7.0

    def test_fetch_after_full_delay_does_not_sleep(self, monkeypatch):
        """Fetching after DOMAIN_DELAY_SECONDS has elapsed does not sleep."""
        current_time = [1000.0]
        sleep_calls = []

        monkeypatch.setattr("pagewatch.ratelimit.time.time", lambda: current_time[0])
        monkeypatch.setattr("pagewatch.ratelimit.time.sleep", lambda s: sleep_calls.append(s))
        monkeypatch.setattr(config, "DOMAIN_DELAY_SECONDS", 10)

        wait_for_domain("example.com")

        # Advance clock by 15 seconds (> 10s)
        current_time[0] = 1015.0

        wait_for_domain("example.com")
        assert len(sleep_calls) == 0


class TestRobotsTxtParsing:
    """Tests for robots.txt parsing and authorization rules."""

    def test_robots_txt_disallows_path(self):
        """Robots.txt disallowing a path denies crawling."""
        robots_content = """
User-agent: *
Disallow: /admin/
Disallow: /private/
"""
        rp = parse_robots_txt("mysite.com", robots_content)

        assert rp.can_fetch("PageWatchBot", "https://mysite.com/admin/settings") is False
        assert rp.can_fetch("PageWatchBot", "https://mysite.com/private/data") is False
        assert rp.can_fetch("PageWatchBot", "https://mysite.com/products/view") is True

    def test_robots_txt_specific_bot_rules(self):
        """Rules specifically for PageWatchBot take precedence."""
        robots_content = """
User-agent: PageWatchBot
Disallow: /bot-forbidden/

User-agent: *
Disallow: /general-forbidden/
"""
        rp = parse_robots_txt("mysite.com", robots_content)

        assert rp.can_fetch("PageWatchBot", "https://mysite.com/bot-forbidden/1") is False
        assert rp.can_fetch("PageWatchBot", "https://mysite.com/general-forbidden/2") is True
        assert rp.can_fetch("PageWatchBot", "https://mysite.com/public") is True

    def test_robots_txt_allow_all(self):
        """Empty disallow allows all paths."""
        robots_content = """
User-agent: *
Disallow:
"""
        rp = parse_robots_txt("mysite.com", robots_content)
        assert rp.can_fetch("PageWatchBot", "https://mysite.com/anywhere") is True

    def test_is_allowed_by_robots_skips_localhost(self, monkeypatch):
        """Localhost URLs are allowed without network calls when ROBOTS_SKIP_LOCALHOST is True."""
        monkeypatch.setattr(config, "ROBOTS_SKIP_LOCALHOST", True)
        assert is_allowed_by_robots("http://127.0.0.1:5001/some-path") is True
        assert is_allowed_by_robots("http://localhost:5000/another-path") is True


class TestApplyBackoff:
    """Tests for HTTP 429/503 exponential backoff logic."""

    def test_backoff_with_integer_retry_after(self):
        """Explicit Retry-After header in seconds sets blocked_until directly."""
        run_write("INSERT INTO urls (id, url, domain, consecutive_failures) VALUES (1, 'https://api.test', 'api.test', 0)")

        before = datetime.now(timezone.utc)
        blocked_iso = apply_backoff(1, retry_after_header="120")
        blocked_dt = datetime.fromisoformat(blocked_iso)

        diff = (blocked_dt - before).total_seconds()
        assert 118 <= diff <= 125

        row = run_query("SELECT blocked_until FROM urls WHERE id = 1")[0]
        assert row["blocked_until"] == blocked_iso

    def test_backoff_exponential_doubling_without_header(self):
        """Without Retry-After header, delay doubles with consecutive failures."""
        run_write("INSERT INTO urls (id, url, domain, consecutive_failures) VALUES (1, 'https://api.test', 'api.test', 2)")

        before = datetime.now(timezone.utc)
        # 60 * 2^2 = 240 seconds
        blocked_iso = apply_backoff(1, retry_after_header=None)
        blocked_dt = datetime.fromisoformat(blocked_iso)

        diff = (blocked_dt - before).total_seconds()
        assert 238 <= diff <= 245
