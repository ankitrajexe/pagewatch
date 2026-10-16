# tests/test_failures.py
# ----------------------
# What it does: Unit tests for failure classification logic (PLAN.md 5.6).
# Talks to: pagewatch/failures.py

import pytest
from pagewatch.failures import classify_fetch, BLOCKED_MARKERS


def make_fetch_dict(ok=True, http_status=200, page_text="This is valid visible page content.", html="<p>Valid content</p>", error_type=None, error_message=None):
    """Helper to build a standardized fetch result dict for testing."""
    return {
        "ok": ok,
        "http_status": http_status,
        "final_url": "https://example.com",
        "html": html,
        "page_text": page_text,
        "screenshot_bytes": b"fake",
        "error_type": error_type,
        "error_message": error_message,
        "duration_ms": 100,
    }


class TestClassifyFetch:
    """Tests for classify_fetch function in failures.py."""

    def test_200_normal_healthy_fetch(self):
        """A normal 200 fetch with adequate text should classify as 'ok'."""
        res = make_fetch_dict(ok=True, http_status=200, page_text="Welcome to our store. We sell widgets and gadgets.")
        classified = classify_fetch(res)
        assert classified["outcome"] == "ok"
        assert classified["message"] == ""

    def test_500_internal_server_error(self):
        """HTTP 500 classifies as outcome 'error'."""
        res = make_fetch_dict(ok=True, http_status=500, page_text="Internal Server Error: Database failure")
        classified = classify_fetch(res)
        assert classified["outcome"] == "error"
        assert "500" in classified["message"]

    def test_404_not_found_error(self):
        """HTTP 404 classifies as outcome 'error'."""
        res = make_fetch_dict(ok=True, http_status=404, page_text="Page not found on this server.")
        classified = classify_fetch(res)
        assert classified["outcome"] == "error"
        assert "404" in classified["message"]

    def test_403_forbidden_blocked(self):
        """HTTP 403 classifies as outcome 'blocked'."""
        res = make_fetch_dict(ok=True, http_status=403, page_text="Forbidden: You do not have permission.")
        classified = classify_fetch(res)
        assert classified["outcome"] == "blocked"
        assert "403" in classified["message"]

    def test_429_too_many_requests_blocked(self):
        """HTTP 429 classifies as outcome 'blocked'."""
        res = make_fetch_dict(ok=True, http_status=429, page_text="Too Many Requests: Rate limit exceeded.")
        classified = classify_fetch(res)
        assert classified["outcome"] == "blocked"
        assert "429" in classified["message"]

    def test_503_service_unavailable_blocked(self):
        """HTTP 503 classifies as outcome 'blocked' (PLAN.md 5.6)."""
        res = make_fetch_dict(ok=True, http_status=503, page_text="Service Unavailable. Please try again later.")
        classified = classify_fetch(res)
        assert classified["outcome"] == "blocked"
        assert "503" in classified["message"]

    def test_captcha_text_in_page_blocked(self):
        """Page containing 'captcha' marker classifies as 'blocked'."""
        res = make_fetch_dict(
            ok=True,
            http_status=200,
            page_text="Please solve the captcha below to prove you are human and proceed."
        )
        classified = classify_fetch(res)
        assert classified["outcome"] == "blocked"
        assert "captcha" in classified["message"].lower()

    def test_cloudflare_just_a_moment_blocked(self):
        """Page containing Cloudflare 'Just a moment...' classifies as 'blocked'."""
        res = make_fetch_dict(
            ok=True,
            http_status=200,
            page_text="Just a moment while we verify your browser security."
        )
        classified = classify_fetch(res)
        assert classified["outcome"] == "blocked"
        assert "just a moment" in classified["message"].lower()

    def test_all_blocked_markers(self):
        """Verify each marker in BLOCKED_MARKERS triggers 'blocked' outcome."""
        for marker in BLOCKED_MARKERS:
            res = make_fetch_dict(
                ok=True,
                http_status=200,
                page_text=f"Security check: {marker}. Please wait a few seconds."
            )
            classified = classify_fetch(res)
            assert classified["outcome"] == "blocked"
            assert marker in classified["message"].lower()

    def test_empty_page_shorter_than_20_chars_error(self):
        """Visible text shorter than 20 characters classifies as 'error' (empty page)."""
        res = make_fetch_dict(
            ok=True,
            http_status=200,
            page_text="Short (12 chrs)"
        )
        classified = classify_fetch(res)
        assert classified["outcome"] == "error"
        assert "Empty page" in classified["message"]

    def test_playwright_timeout_error_type(self):
        """Timeout error_type classifies as 'error' with timeout description."""
        res = make_fetch_dict(
            ok=False,
            http_status=None,
            error_type="timeout",
            error_message="Page took too long to load (timeout)"
        )
        classified = classify_fetch(res)
        assert classified["outcome"] == "error"
        assert "timeout" in classified["message"].lower()

    def test_dns_network_error(self):
        """DNS lookup failure classifies as 'error'."""
        res = make_fetch_dict(
            ok=False,
            http_status=None,
            error_type="dns",
            error_message="Could not find this website (DNS error)"
        )
        classified = classify_fetch(res)
        assert classified["outcome"] == "error"
        assert "DNS" in classified["message"]
