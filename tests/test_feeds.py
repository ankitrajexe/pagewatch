# test_feeds.py
# -------------
# Tests for per-page RSS 2.0 feeds bonus feature:
# 1. format_rfc822 date helper.
# 2. generate_rss_feed XML structure, channels, items, GUIDs, and latest 50 cap.
# 3. HTTP routes /monitor/<id>/feed.xml and /monitors/<id>/feed.xml.
# 4. Checker integration verifying snapshots.summary is populated.
# 5. Monitor detail page rendering with visible RSS link and alternate head link.

import xml.etree.ElementTree as ET
import pytest
from pagewatch import init, config
from pagewatch.db import create_tables, run_query, run_write
from pagewatch import monitors_repo
from pagewatch.feeds import format_rfc822, generate_rss_feed
from pagewatch.checker import check_monitor


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Configure an isolated temporary database and file directories for every test."""
    db_file = str(tmp_path / "feeds_test.db")
    texts_dir = str(tmp_path / "texts")
    shots_dir = str(tmp_path / "screenshots")

    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr("pagewatch.db.DB_PATH", db_file)
    monkeypatch.setattr(config, "TEXT_DIR", texts_dir)
    monkeypatch.setattr(config, "SCREENSHOT_DIR", shots_dir)
    monkeypatch.setattr(config, "ALLOW_LOCALHOST", True)
    monkeypatch.setattr(config, "BASE_URL", "http://localhost:5000")

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
# 1. RFC 822 date formatting tests
# ---------------------------------------------------------------------------

def test_format_rfc822():
    # ISO string with UTC Z
    rfc = format_rfc822("2026-10-16T15:30:00Z")
    assert "16 Oct 2026 15:30:00" in rfc
    assert "+0000" in rfc or "GMT" in rfc

    # Graceful handling for None and invalid inputs
    rfc_none = format_rfc822(None)
    assert "2026" in rfc_none or "20" in rfc_none

    rfc_invalid = format_rfc822("not-a-date")
    assert isinstance(rfc_invalid, str) and len(rfc_invalid) > 10


# ---------------------------------------------------------------------------
# 2. RSS 2.0 XML generation tests
# ---------------------------------------------------------------------------

def test_generate_rss_feed_empty():
    monitor_id = monitors_repo.create_monitor({
        "name": "Empty Monitor",
        "url": "https://example.com/blog",
        "interval_minutes": 60,
    })
    monitor = monitors_repo.get_monitor(monitor_id)

    xml_str = generate_rss_feed(monitor)
    assert xml_str.startswith("<?xml")

    # Parse with standard library xml.etree.ElementTree
    root = ET.fromstring(xml_str)
    assert root.tag == "rss"
    assert root.attrib.get("version") == "2.0"

    channel = root.find("channel")
    assert channel is not None
    assert channel.find("title").text == "Empty Monitor"
    assert channel.find("link").text == f"http://localhost:5000/monitors/{monitor_id}"
    assert channel.find("language").text == "en"
    assert len(channel.findall("item")) == 0


def test_generate_rss_feed_with_snapshots():
    monitor_id = monitors_repo.create_monitor({
        "name": "Tech News",
        "url": "https://example.com/news",
        "interval_minutes": 30,
    })
    monitor = monitors_repo.get_monitor(monitor_id)

    # Insert baseline snapshot and two change snapshots
    s1 = run_write(
        """
        INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path, text_length, summary)
        VALUES (?, '2026-10-16T10:00:00Z', 'hash1', '', '', 100, 'Baseline snapshot created')
        """,
        (monitor_id,)
    )
    s2 = run_write(
        """
        INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path, text_length, summary)
        VALUES (?, '2026-10-16T11:00:00Z', 'hash2', '', '', 120, 'Price changed from 499 to 399')
        """,
        (monitor_id,)
    )
    s3 = run_write(
        """
        INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path, text_length, summary)
        VALUES (?, '2026-10-16T12:00:00Z', 'hash3', '', '', 150, '3 lines added, 1 removed')
        """,
        (monitor_id,)
    )

    xml_str = generate_rss_feed(monitor)
    root = ET.fromstring(xml_str)
    channel = root.find("channel")
    items = channel.findall("item")

    # Should have 3 items ordered newest first (s3, s2, s1)
    assert len(items) == 3

    # Check Item 1 (newest: s3)
    assert items[0].find("title").text == "3 lines added, 1 removed"
    assert items[0].find("guid").text == str(s3)
    assert items[0].find("guid").attrib.get("isPermaLink") == "false"
    assert f"compare?a={s2}&b={s3}" in items[0].find("link").text
    assert "3 lines added, 1 removed" in items[0].find("description").text

    # Check Item 2 (s2)
    assert items[1].find("title").text == "Price changed from 499 to 399"
    assert items[1].find("guid").text == str(s2)
    assert f"compare?a={s1}&b={s2}" in items[1].find("link").text

    # Check Item 3 (baseline: s1)
    assert items[2].find("title").text == "Baseline snapshot created"
    assert items[2].find("guid").text == str(s1)
    assert items[2].find("link").text == f"http://localhost:5000/monitors/{monitor_id}"


def test_generate_rss_feed_limits_to_50_items():
    monitor_id = monitors_repo.create_monitor({
        "name": "High Volume Feed",
        "url": "https://example.com/feed-test",
        "interval_minutes": 15,
    })
    monitor = monitors_repo.get_monitor(monitor_id)

    # Insert 60 snapshots
    for i in range(1, 61):
        run_write(
            """
            INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path, text_length, summary)
            VALUES (?, ?, ?, '', '', 50, ?)
            """,
            (monitor_id, f"2026-10-16T10:{i:02d}:00Z", f"hash_{i}", f"Change #{i}")
        )

    xml_str = generate_rss_feed(monitor)
    root = ET.fromstring(xml_str)
    channel = root.find("channel")
    items = channel.findall("item")

    # Must be capped at exactly 50 items
    assert len(items) == 50
    # First item should be snapshot #60
    assert items[0].find("title").text == "Change #60"
    # 50th item should be snapshot #11
    assert items[49].find("title").text == "Change #11"


# ---------------------------------------------------------------------------
# 3. HTTP feed routes tests
# ---------------------------------------------------------------------------

def test_rss_feed_http_routes(client):
    monitor_id = monitors_repo.create_monitor({
        "name": "Route RSS Monitor",
        "url": "https://example.com/item",
        "interval_minutes": 60,
    })

    # Both /monitor/<id>/feed.xml and /monitors/<id>/feed.xml work
    res1 = client.get(f"/monitor/{monitor_id}/feed.xml")
    assert res1.status_code == 200
    assert "application/rss+xml" in res1.mimetype
    assert b"<rss version=\"2.0\">" in res1.data
    assert b"<title>Route RSS Monitor</title>" in res1.data

    res2 = client.get(f"/monitors/{monitor_id}/feed.xml")
    assert res2.status_code == 200
    assert "application/rss+xml" in res2.mimetype

    # 404 for nonexistent monitor
    res_404 = client.get("/monitors/99999/feed.xml")
    assert res_404.status_code == 404


# ---------------------------------------------------------------------------
# 4. Checker integration test for snapshots.summary
# ---------------------------------------------------------------------------

def test_checker_populates_snapshots_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TEXT_DIR", str(tmp_path / "texts"))
    monkeypatch.setattr(config, "SCREENSHOT_DIR", str(tmp_path / "screenshots"))

    monitor_id = monitors_repo.create_monitor({
        "name": "Summary Checker Monitor",
        "url": "https://example.com/product",
        "interval_minutes": 60,
    })
    monitor = monitors_repo.get_monitor(monitor_id)

    # 1. Baseline check -> summary must be 'Baseline snapshot created'
    res1 = check_monitor(monitor, {
        "ok": True,
        "html": "<html><body><p>Price: $100</p></body></html>",
        "status": 200,
        "duration_ms": 100,
        "screenshot_bytes": b"fake-png"
    })
    assert res1["outcome"] == "changed"

    rows1 = run_query("SELECT * FROM snapshots WHERE id = ?", (res1["snapshot_id"],))
    assert rows1[0]["summary"] == "Baseline snapshot created"

    # 2. Meaningful change -> summary must be populated using make_summary
    monitor = monitors_repo.get_monitor(monitor_id)
    res2 = check_monitor(monitor, {
        "ok": True,
        "html": "<html><body><p>Price: $150</p></body></html>",
        "status": 200,
        "duration_ms": 110,
        "screenshot_bytes": b"fake-png"
    })
    assert res2["outcome"] == "changed"

    rows2 = run_query("SELECT * FROM snapshots WHERE id = ?", (res2["snapshot_id"],))
    assert rows2[0]["summary"] != ""
    assert "100" in rows2[0]["summary"] and "150" in rows2[0]["summary"]


# ---------------------------------------------------------------------------
# 5. Monitor detail UI test (visible RSS link and head tag)
# ---------------------------------------------------------------------------

def test_monitor_page_renders_rss_links(client):
    monitor_id = monitors_repo.create_monitor({
        "name": "UI RSS Monitor",
        "url": "https://example.com/ui-test",
        "interval_minutes": 60,
    })

    res = client.get(f"/monitors/{monitor_id}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Visible button / link
    assert f'href="/monitors/{monitor_id}/feed.xml"' in html
    assert "RSS Feed" in html

    # <link rel="alternate" type="application/rss+xml" ...> tag in head
    assert '<link rel="alternate" type="application/rss+xml"' in html
    assert f'href="/monitors/{monitor_id}/feed.xml"' in html
