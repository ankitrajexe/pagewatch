# tests/test_monitors_web.py
# -------------------------
# What it does: Unit and integration tests for monitors repository and web UI routes.
# Talks to: pagewatch/monitors_repo.py, pagewatch/web/routes.py, pagewatch/__init__.py

import os
import pytest
from pagewatch import init
from pagewatch import monitors_repo
from pagewatch.db import run_query


@pytest.fixture
def app(tmp_path, monkeypatch):
    """
    Create a clean Flask test application with a temporary database.
    """
    test_db = str(tmp_path / "test_pagewatch.db")
    monkeypatch.setattr("pagewatch.config.DB_PATH", test_db)
    monkeypatch.setattr("pagewatch.db.DB_PATH", test_db)
    monkeypatch.setattr("pagewatch.config.ALLOW_LOCALHOST", True)

    app = init(start_worker=False, start_scheduler_thread=False)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


class TestMonitorsRepo:
    """Tests for database operations in monitors_repo."""

    def test_create_and_deduplicate_urls(self, app):
        """Two monitors watching the same URL should share one URL row in 'urls'."""
        data1 = {
            "name": "Monitor A",
            "url": "https://example.com/items/",
            "interval_minutes": 30,
            "sensitivity": "medium",
        }
        data2 = {
            "name": "Monitor B",
            "url": "https://example.com/items#top",  # normalizes to same URL
            "interval_minutes": 60,
            "sensitivity": "high",
        }
        id1 = monitors_repo.create_monitor(data1)
        id2 = monitors_repo.create_monitor(data2)

        # Check URL table has only 1 row
        urls = run_query("SELECT * FROM urls")
        assert len(urls) == 1
        assert urls[0]["url"] == "https://example.com/items"

        # Check monitors table has 2 rows pointing to that same url_id
        m1 = monitors_repo.get_monitor(id1)
        m2 = monitors_repo.get_monitor(id2)
        assert m1["url_id"] == urls[0]["id"]
        assert m2["url_id"] == urls[0]["id"]
        assert m1["status"] == "pending"

    def test_update_and_delete_monitor(self, app):
        """Updating monitor changes its fields, delete removes it."""
        mid = monitors_repo.create_monitor({
            "name": "Original Name",
            "url": "https://example.org/test",
            "interval_minutes": 15,
            "sensitivity": "low",
        })

        monitors_repo.update_monitor(mid, {
            "name": "Updated Name",
            "url": "https://example.org/new-test",
            "interval_minutes": 120,
            "sensitivity": "high",
        })

        updated = monitors_repo.get_monitor(mid)
        assert updated["name"] == "Updated Name"
        assert updated["url"] == "https://example.org/new-test"
        assert updated["sensitivity"] == "high"

        # Delete
        monitors_repo.delete_monitor(mid)
        assert monitors_repo.get_monitor(mid) is None


class TestWebRoutes:
    """Tests for Flask web UI endpoints."""

    def test_dashboard_empty(self, client):
        """Dashboard renders with 0 monitors initially."""
        res = client.get("/")
        assert res.status_code == 200
        assert b"Total active monitors: <strong>0</strong>" in res.data
        assert b"No monitors configured" in res.data

    def test_add_monitor_validation_errors(self, client):
        """Submitting empty name or invalid URL shows friendly error messages."""
        res = client.post("/monitors/add", data={
            "name": "",
            "url": "not-a-valid-url",
            "interval_minutes": "15",
        })
        assert res.status_code == 200
        assert b"Monitor name is required." in res.data
        assert b"URL must start with http:// or https://" in res.data

    def test_add_monitor_success(self, client):
        """Valid form submission creates monitor and redirects to dashboard."""
        res = client.post("/monitors/add", data={
            "name": "Test Site Watcher",
            "url": "http://127.0.0.1:5001/",
            "interval_minutes": "30",
            "sensitivity": "medium",
            "include_selectors": "p.price",
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"Test Site Watcher" in res.data
        assert b"PENDING" in res.data
        assert b"30 min" in res.data

    def test_view_monitor_details(self, client):
        """Viewing a monitor displays its configuration."""
        mid = monitors_repo.create_monitor({
            "name": "Detail Test",
            "url": "https://test.org/product",
            "interval_minutes": 60,
            "sensitivity": "medium",
            "include_selectors": "div.content",
        })
        res = client.get(f"/monitors/{mid}")
        assert res.status_code == 200
        assert b"Detail Test" in res.data
        assert b"https://test.org/product" in res.data
        assert b"div.content" in res.data

    def test_edit_monitor_route(self, client):
        """GET edit form pre-populates data, POST updates it."""
        mid = monitors_repo.create_monitor({
            "name": "Before Edit",
            "url": "https://test.org/page1",
            "interval_minutes": 15,
        })
        # GET edit
        get_res = client.get(f"/monitors/{mid}/edit")
        assert get_res.status_code == 200
        assert b"Before Edit" in get_res.data

        # POST edit
        post_res = client.post(f"/monitors/{mid}/edit", data={
            "name": "After Edit",
            "url": "https://test.org/page2",
            "interval_minutes": 60,
            "sensitivity": "high",
        }, follow_redirects=True)
        assert post_res.status_code == 200
        assert b"After Edit" in post_res.data

    def test_delete_confirmation_and_post(self, client):
        """GET delete renders confirmation; POST deletes monitor."""
        mid = monitors_repo.create_monitor({
            "name": "To Be Deleted",
            "url": "https://test.org/delete-me",
            "interval_minutes": 15,
        })
        # Confirm page
        confirm_res = client.get(f"/monitors/{mid}/delete")
        assert confirm_res.status_code == 200
        assert b"Confirm Deletion" in confirm_res.data
        assert b"To Be Deleted" in confirm_res.data

        # Perform deletion
        del_res = client.post(f"/monitors/{mid}/delete", follow_redirects=True)
        assert del_res.status_code == 200
        assert b"To Be Deleted" not in del_res.data

    def test_delete_monitor_cleans_up_files_and_db_records(self, tmp_path, app):
        """Deleting a monitor must delete its snapshots, text/image files from disk, and db rows."""
        mid = monitors_repo.create_monitor({
            "name": "File Cleanup Monitor",
            "url": "https://test.org/cleanup",
            "interval_minutes": 15,
        })

        # Create dummy text and screenshot files on disk
        txt_file = tmp_path / "dummy.txt"
        png_file = tmp_path / "dummy.png"
        txt_file.write_text("dummy text content", encoding="utf-8")
        png_file.write_bytes(b"dummy png bytes")

        from pagewatch.db import run_write, run_query
        snap_id = run_write(
            """
            INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path)
            VALUES (?, '2026-10-16T12:00:00Z', 'hash', ?, ?)
            """,
            (mid, str(txt_file), str(png_file))
        )
        assert os.path.isfile(str(txt_file))
        assert os.path.isfile(str(png_file))

        # Perform deletion
        monitors_repo.delete_monitor(mid)

        # Files on disk must be deleted
        assert not os.path.isfile(str(txt_file))
        assert not os.path.isfile(str(png_file))

        # DB rows must be gone
        assert len(run_query("SELECT * FROM monitors WHERE id = ?", (mid,))) == 0
        assert len(run_query("SELECT * FROM snapshots WHERE monitor_id = ?", (mid,))) == 0
