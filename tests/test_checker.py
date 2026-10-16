# tests/test_checker.py
# ----------------------
# What it does: Unit tests for the checker pipeline (check_monitor) using
#               fake fetch results without requiring a real browser.
# Talks to: pagewatch/checker.py, pagewatch/db.py, pagewatch/config.py

import os
import pytest
from pagewatch import config
from pagewatch.db import create_tables, run_query
from pagewatch.checker import check_monitor
from pagewatch.monitors_repo import create_monitor, get_monitor


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """
    Configure a temporary database and file directories for every test.
    """
    db_file = str(tmp_path / "checker_test.db")
    texts_dir = str(tmp_path / "texts")
    shots_dir = str(tmp_path / "screenshots")

    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr("pagewatch.db.DB_PATH", db_file)
    monkeypatch.setattr(config, "TEXT_DIR", texts_dir)
    monkeypatch.setattr(config, "SCREENSHOT_DIR", shots_dir)
    monkeypatch.setattr(config, "ALLOW_LOCALHOST", True)

    create_tables()


def make_fake_fetch(html, ok=True, http_status=200, error_message=None):
    """Helper to construct a mock fetch_result dictionary."""
    return {
        "ok": ok,
        "http_status": http_status,
        "final_url": "http://127.0.0.1:5001/",
        "html": html,
        "page_text": "placeholder text",
        "screenshot_bytes": b"fake-png-bytes",
        "error_type": None if ok else "connection",
        "error_message": error_message,
        "duration_ms": 120,
    }


class TestCheckerPipeline:
    """Tests for checker.py check_monitor function."""

    def test_baseline_created_on_first_check(self):
        """First check must create a baseline snapshot without an alert flag."""
        mid = create_monitor({
            "name": "Store Test",
            "url": "http://127.0.0.1:5001/",
            "interval_minutes": 30,
            "sensitivity": "medium",
        })
        m = get_monitor(mid)

        html = "<html><body><h1>Store</h1><p>Price: $499</p></body></html>"
        fetch_res = make_fake_fetch(html)

        result = check_monitor(m, fetch_res)

        assert result["outcome"] == "changed"
        assert result["message"] == "Baseline snapshot created"
        assert result["snapshot_id"] is not None

        # Verify database record
        snapshots = run_query("SELECT * FROM snapshots WHERE monitor_id = ?", (mid,))
        assert len(snapshots) == 1
        assert snapshots[0]["text_length"] > 0
        assert os.path.exists(snapshots[0]["text_path"])
        assert os.path.exists(snapshots[0]["screenshot_path"])

        # Verify monitor updated
        updated_m = get_monitor(mid)
        assert updated_m["status"] == "ok"
        assert updated_m["last_checked_at"] is not None
        assert updated_m["last_changed_at"] is not None

    def test_unchanged_hash_does_not_create_snapshot(self):
        """Second check with identical content should not store a new snapshot."""
        mid = create_monitor({
            "name": "Store Test",
            "url": "http://127.0.0.1:5001/",
            "interval_minutes": 30,
            "sensitivity": "medium",
        })
        m = get_monitor(mid)

        html = "<html><body><h1>Store</h1><p>Price: $499</p><p>2026-10-16 12:00:00</p></body></html>"
        # First check (baseline)
        check_monitor(m, make_fake_fetch(html))

        # Second check with timestamp noise changing (normalized text is identical)
        html_v2 = "<html><body><h1>Store</h1><p>Price: $499</p><p>2026-10-16 13:45:00</p></body></html>"
        m = get_monitor(mid)
        result = check_monitor(m, make_fake_fetch(html_v2))

        assert result["outcome"] == "unchanged"
        assert result["snapshot_id"] is None

        # Snapshots table should still only have 1 entry
        snapshots = run_query("SELECT * FROM snapshots WHERE monitor_id = ?", (mid,))
        assert len(snapshots) == 1

    def test_meaningful_change_creates_new_snapshot(self):
        """Meaningful price change creates a second snapshot."""
        mid = create_monitor({
            "name": "Store Test",
            "url": "http://127.0.0.1:5001/",
            "interval_minutes": 30,
            "sensitivity": "medium",
        })
        m = get_monitor(mid)

        html1 = "<html><body><h1>Store</h1><p>Price: $499</p></body></html>"
        check_monitor(m, make_fake_fetch(html1))

        # Real change
        html2 = "<html><body><h1>Store</h1><p>Price: $999</p></body></html>"
        m = get_monitor(mid)
        result = check_monitor(m, make_fake_fetch(html2))

        assert result["outcome"] == "changed"
        assert result["snapshot_id"] is not None
        assert "Content changed" in result["message"]

        snapshots = run_query("SELECT * FROM snapshots WHERE monitor_id = ?", (mid,))
        assert len(snapshots) == 2

    def test_below_sensitivity_change_does_not_create_snapshot(self):
        """Change below sensitivity threshold is logged as unchanged."""
        mid = create_monitor({
            "name": "Large Doc",
            "url": "http://127.0.0.1:5001/doc",
            "interval_minutes": 60,
            "sensitivity": "medium",  # requires >= 2% change
        })
        m = get_monitor(mid)

        # Baseline with 200 lines
        lines_baseline = [f"<p>Document paragraph {i}</p>" for i in range(200)]
        html_baseline = "<html><body>" + "".join(lines_baseline) + "</body></html>"
        check_monitor(m, make_fake_fetch(html_baseline))

        # Modify only 1 line out of 200 (1 line change / 200 = 0.5%, below 2%)
        lines_v2 = list(lines_baseline)
        lines_v2[100] = "<p>Document paragraph MODIFIED</p>"
        html_v2 = "<html><body>" + "".join(lines_v2) + "</body></html>"

        m = get_monitor(mid)
        result = check_monitor(m, make_fake_fetch(html_v2))

        assert result["outcome"] == "unchanged"
        assert result["message"] == "below sensitivity"
        assert result["snapshot_id"] is None

        # Still only 1 snapshot in database
        snapshots = run_query("SELECT * FROM snapshots WHERE monitor_id = ?", (mid,))
        assert len(snapshots) == 1

    def test_include_selector_no_match_treated_as_error(self):
        """If include_selectors is specified but matches nothing, report as error."""
        mid = create_monitor({
            "name": "Missing Region Test",
            "url": "http://127.0.0.1:5001/",
            "interval_minutes": 15,
            "include_selectors": "div.missing-class-xyz",
        })
        m = get_monitor(mid)

        html = "<html><body><h1>Only This</h1></body></html>"
        result = check_monitor(m, make_fake_fetch(html))

        assert result["outcome"] == "error"
        assert result["message"] == "Selector matched nothing"

        updated_m = get_monitor(mid)
        assert updated_m["status"] == "error"
        assert updated_m["status_message"] == "Selector matched nothing"

    def test_fetch_failure_records_error(self):
        """When fetch_result.ok is False, update monitor status to error."""
        mid = create_monitor({
            "name": "Failing Test",
            "url": "http://127.0.0.1:5001/down",
            "interval_minutes": 15,
        })
        m = get_monitor(mid)

        result = check_monitor(
            m,
            make_fake_fetch("", ok=False, http_status=500, error_message="Internal Server Error")
        )

        assert result["outcome"] == "error"
        assert "Internal Server Error" in result["message"]

        updated_m = get_monitor(mid)
        assert updated_m["status"] == "error"
        assert updated_m["consecutive_failures"] == 1

    def test_large_page_text_limited_to_1mb(self):
        """Pages with huge text content must be truncated to 1 MB."""
        mid = create_monitor({
            "name": "Huge Page Monitor",
            "url": "http://127.0.0.1:5001/huge",
            "interval_minutes": 15,
        })
        m = get_monitor(mid)

        # 1.5 MB of natural paragraph text (so noise filter doesn't replace as [TOKEN])
        sample_sentence = "The quick brown fox jumps over the lazy dog. Continuous monitoring and change detection.\n"
        large_html = "<html><body><p>" + sample_sentence * 18000 + "</p></body></html>"
        res = check_monitor(m, make_fake_fetch(large_html))

        assert res["outcome"] == "changed"
        snap_id = res["snapshot_id"]
        row = run_query("SELECT text_path, text_length FROM snapshots WHERE id = ?", (snap_id,))[0]

        with open(row["text_path"], "r", encoding="utf-8") as f:
            content = f.read()

        assert "[Truncated: page text exceeded 1 MB limit]" in content
        # Base text must not exceed 1 MB
        assert len(content.encode("utf-8")) <= (1024 * 1024 + 100)
