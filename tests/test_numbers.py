# test_numbers.py
# ---------------
# Tests for number tracking bonus feature:
# 1. parse_number parsing across 15+ international formats.
# 2. extract_number_from_html with CSS selectors.
# 3. record_number_point in database (including unchanged checks).
# 4. Threshold alerts (number_alert_below and number_alert_above) with deduplication.
# 5. Line chart generation via Matplotlib (Agg backend).
# 6. HTTP chart route /monitors/<id>/chart.png and /monitor/<id>/chart.png.
# 7. End-to-end integration with check_monitor.

import os
import pytest
from pagewatch import init, config
from pagewatch.db import create_tables, run_query, run_write
from pagewatch import monitors_repo
from pagewatch.numbers import (
    parse_number,
    extract_number_from_html,
    record_number_point,
    check_and_alert_thresholds,
    generate_number_chart,
)
from pagewatch.checker import check_monitor


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Configure a temporary database and file directories for every test."""
    db_file = str(tmp_path / "numbers_test.db")
    texts_dir = str(tmp_path / "texts")
    shots_dir = str(tmp_path / "screenshots")

    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr("pagewatch.db.DB_PATH", db_file)
    monkeypatch.setattr(config, "TEXT_DIR", texts_dir)
    monkeypatch.setattr(config, "SCREENSHOT_DIR", shots_dir)
    monkeypatch.setattr(config, "ALLOW_LOCALHOST", True)

    create_tables()


@pytest.fixture
def app():
    app_instance = init(start_worker=False, start_scheduler_thread=False)
    app_instance.config["TESTING"] = True
    return app_instance


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# 1. parse_number unit tests (15+ formats)
# ---------------------------------------------------------------------------

def test_parse_number_indian_rupee():
    assert parse_number("₹1,299.50") == 1299.50
    assert parse_number("₹ 1,299.50") == 1299.50


def test_parse_number_indian_comma_grouping():
    # Indian numbering format: 1,23,456 (lakhs)
    assert parse_number("1,23,456") == 123456.0
    assert parse_number("1,23,456.75") == 123456.75


def test_parse_number_us_dollar():
    assert parse_number("$ 499") == 499.0
    assert parse_number("$12.99/mo") == 12.99
    assert parse_number("$10,000") == 10000.0


def test_parse_number_ratings_and_percentages():
    assert parse_number("4.5 stars") == 4.5
    assert parse_number("99.5%") == 99.5


def test_parse_number_stock_and_text():
    assert parse_number("Only 3 left in stock") == 3.0
    assert parse_number("Items remaining: 42") == 42.0


def test_parse_number_european_format():
    # European comma decimal and dot thousand separators
    assert parse_number("€ 99,99") == 99.99
    assert parse_number("1.234,50 €") == 1234.50


def test_parse_number_negative_values():
    assert parse_number("-42") == -42.0
    assert parse_number("- 15.5") == -15.5


def test_parse_number_integers_and_decimals():
    assert parse_number("100") == 100.0
    assert parse_number("0.05") == 0.05
    assert parse_number("0") == 0.0
    assert parse_number("+250.75") == 250.75


def test_parse_number_no_numbers():
    assert parse_number("Free") is None
    assert parse_number("Out of stock") is None
    assert parse_number("") is None
    assert parse_number(None) is None
    assert parse_number("No digits here at all!") is None


# ---------------------------------------------------------------------------
# 2. extract_number_from_html tests
# ---------------------------------------------------------------------------

def test_extract_number_from_html():
    html = """
    <html>
      <body>
        <div class="product">
          <span class="title">Gadget</span>
          <span class="price">₹ 1,499.00</span>
          <span class="rating">4.8 out of 5 stars</span>
        </div>
      </body>
    </html>
    """
    assert extract_number_from_html(html, ".price") == 1499.0
    assert extract_number_from_html(html, ".rating") == 4.8
    assert extract_number_from_html(html, ".title") is None
    assert extract_number_from_html(html, ".nonexistent") is None
    assert extract_number_from_html("", ".price") is None
    assert extract_number_from_html(html, "") is None


# ---------------------------------------------------------------------------
# 3. record_number_point tests
# ---------------------------------------------------------------------------

def test_record_number_point_persistence():
    monitor_id = monitors_repo.create_monitor({
        "name": "Point Monitor",
        "url": "https://example.com/item",
        "interval_minutes": 60,
        "number_selector": ".price"
    })

    snap_id = run_write(
        """
        INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path, text_length)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (monitor_id, "2026-10-16T10:00:00Z", "hash1", "", "", 10)
    )

    # Record point with snapshot_id
    point_id_1 = record_number_point(monitor_id, snap_id, 499.50, "2026-10-16T10:00:00Z")
    assert point_id_1 > 0

    # Record point without snapshot_id (unchanged check)
    point_id_2 = record_number_point(monitor_id, None, 499.50, "2026-10-16T11:00:00Z")
    assert point_id_2 > 0

    rows = run_query(
        "SELECT * FROM number_points WHERE monitor_id = ? ORDER BY id ASC",
        (monitor_id,)
    )
    assert len(rows) == 2
    assert rows[0]["value"] == 499.50
    assert rows[0]["snapshot_id"] == snap_id
    assert rows[1]["value"] == 499.50
    assert rows[1]["snapshot_id"] is None


# ---------------------------------------------------------------------------
# 4. Threshold alerting tests
# ---------------------------------------------------------------------------

def test_threshold_alert_below(monkeypatch):
    sent_emails = []

    def fake_send_email(to, subject, body):
        sent_emails.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("pagewatch.numbers.send_email", fake_send_email)

    monitor_id = monitors_repo.create_monitor({
        "name": "Price Drop Monitor",
        "url": "https://example.com/sale",
        "interval_minutes": 60,
        "number_selector": ".price",
        "number_alert_below": 500.0,
        "alert_email": "alerts@example.com"
    })
    monitor = monitors_repo.get_monitor(monitor_id)

    # 1. Price is 550 -> above threshold, no alert
    alerted = check_and_alert_thresholds(monitor, 550.0)
    assert alerted is False
    assert len(sent_emails) == 0

    # 2. Price drops to 450 -> triggers alert
    alerted = check_and_alert_thresholds(monitor, 450.0)
    assert alerted is True
    assert len(sent_emails) == 1
    assert "dropped below threshold 500.0" in sent_emails[0]["body"]

    # 3. Repeat check with 450 -> deduplicated, does not re-alert
    alerted_again = check_and_alert_thresholds(monitor, 450.0)
    assert alerted_again is False
    assert len(sent_emails) == 1

    # 4. Price drops further to 400 -> new value, triggers alert
    alerted_new = check_and_alert_thresholds(monitor, 400.0)
    assert alerted_new is True
    assert len(sent_emails) == 2
    assert "dropped below threshold 500.0" in sent_emails[1]["body"]


def test_threshold_alert_above(monkeypatch):
    sent_telegrams = []

    def fake_send_telegram(chat_id, text):
        sent_telegrams.append({"chat_id": chat_id, "text": text})
        return True

    monkeypatch.setattr("pagewatch.numbers.send_telegram", fake_send_telegram)

    monitor_id = monitors_repo.create_monitor({
        "name": "Temperature Monitor",
        "url": "https://example.com/temp",
        "interval_minutes": 15,
        "number_selector": ".temp",
        "number_alert_above": 35.0,
        "telegram_chat_id": "123456789"
    })
    monitor = monitors_repo.get_monitor(monitor_id)

    # 1. Temp is 30 -> below threshold, no alert
    assert check_and_alert_thresholds(monitor, 30.0) is False
    assert len(sent_telegrams) == 0

    # 2. Temp spikes to 38.5 -> triggers alert
    assert check_and_alert_thresholds(monitor, 38.5) is True
    assert len(sent_telegrams) == 1
    assert "rose above threshold 35.0" in sent_telegrams[0]["text"]


# ---------------------------------------------------------------------------
# 5. Chart generation tests
# ---------------------------------------------------------------------------

def test_generate_number_chart_empty():
    monitor_id = monitors_repo.create_monitor({
        "name": "Empty Chart Monitor",
        "url": "https://example.com",
        "interval_minutes": 60,
        "number_selector": ".val"
    })
    monitor = monitors_repo.get_monitor(monitor_id)
    png_bytes = generate_number_chart(monitor)

    assert isinstance(png_bytes, bytes)
    # Check PNG magic header
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_generate_number_chart_with_data_and_thresholds():
    monitor_id = monitors_repo.create_monitor({
        "name": "Active Chart Monitor",
        "url": "https://example.com",
        "interval_minutes": 60,
        "number_selector": ".price",
        "number_alert_below": 200.0,
        "number_alert_above": 500.0
    })
    monitor = monitors_repo.get_monitor(monitor_id)

    # Insert a few sample points
    record_number_point(monitor_id, None, 250.0, "2026-10-16T10:00:00")
    record_number_point(monitor_id, None, 280.0, "2026-10-16T11:00:00")
    record_number_point(monitor_id, None, 310.0, "2026-10-16T12:00:00")

    png_bytes = generate_number_chart(monitor)
    assert isinstance(png_bytes, bytes)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    # Verify non-empty and reasonably sized image
    assert len(png_bytes) > 1000


# ---------------------------------------------------------------------------
# 6. Chart HTTP route tests
# ---------------------------------------------------------------------------

def test_chart_http_routes(client):
    monitor_id = monitors_repo.create_monitor({
        "name": "Route Chart Monitor",
        "url": "https://example.com",
        "interval_minutes": 60,
        "number_selector": ".price"
    })

    # Both /monitors/<id>/chart.png and /monitor/<id>/chart.png work
    res1 = client.get(f"/monitors/{monitor_id}/chart.png")
    assert res1.status_code == 200
    assert res1.mimetype == "image/png"
    assert res1.data.startswith(b"\x89PNG\r\n\x1a\n")

    res2 = client.get(f"/monitor/{monitor_id}/chart.png")
    assert res2.status_code == 200
    assert res2.mimetype == "image/png"

    # 404 on missing monitor
    res_404 = client.get("/monitors/99999/chart.png")
    assert res_404.status_code == 404


# ---------------------------------------------------------------------------
# 7. Checker integration tests (baseline and unchanged check point recording)
# ---------------------------------------------------------------------------

def test_checker_records_number_points_baseline_and_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TEXT_DIR", str(tmp_path / "texts"))
    monkeypatch.setattr(config, "SCREENSHOT_DIR", str(tmp_path / "screenshots"))

    monitor_id = monitors_repo.create_monitor({
        "name": "Checker Number Monitor",
        "url": "https://example.com/shop",
        "interval_minutes": 60,
        "number_selector": ".product-price",
        "number_alert_below": 200.0
    })
    monitor = monitors_repo.get_monitor(monitor_id)

    html_content = """
    <html>
      <body>
        <h1>Product</h1>
        <p class="product-price">₹ 299.00</p>
      </body>
    </html>
    """

    fetch_result = {
        "ok": True,
        "html": html_content,
        "status": 200,
        "duration_ms": 120,
        "screenshot_bytes": b"fake-png-data"
    }

    # 1. Baseline check -> creates baseline snapshot and records first number point
    res1 = check_monitor(monitor, fetch_result)
    assert res1["outcome"] == "changed"

    points1 = run_query("SELECT * FROM number_points WHERE monitor_id = ?", (monitor_id,))
    assert len(points1) == 1
    assert points1[0]["value"] == 299.0
    assert points1[0]["snapshot_id"] == res1["snapshot_id"]

    # 2. Second check with identical content -> outcome 'unchanged', but records a second point!
    monitor = monitors_repo.get_monitor(monitor_id)
    res2 = check_monitor(monitor, fetch_result)
    assert res2["outcome"] == "unchanged"

    points2 = run_query("SELECT * FROM number_points WHERE monitor_id = ? ORDER BY id ASC", (monitor_id,))
    assert len(points2) == 2
    assert points2[1]["value"] == 299.0
    assert points2[1]["snapshot_id"] is None
