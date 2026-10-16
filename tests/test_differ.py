# tests/test_differ.py
# --------------------
# What it does: Unit tests for text differencing (unified and side-by-side diffs),
#               and safe file serving with path traversal protection.
# Talks to: pagewatch/differ.py, pagewatch/web/routes.py.

import os
import pytest
from pagewatch import config
from pagewatch.differ import text_diff_lines, count_diff_lines, side_by_side_html
from pagewatch.web.routes import bp
from flask import Flask


class TestTextDiffer:
    """Tests for text_diff_lines, count_diff_lines, and side_by_side_html."""

    def test_text_diff_lines_detects_additions_and_removals(self):
        """text_diff_lines correctly classifies lines as same, added, or removed."""
        old_text = "Apple\nBanana\nCherry"
        new_text = "Apple\nBlueberry\nCherry\nDate"

        diff = text_diff_lines(old_text, new_text)

        # Check types
        assert isinstance(diff, list)
        for kind, text in diff:
            assert kind in ("same", "added", "removed")

        # Specific line checks
        kinds_by_text = {}
        for kind, text in diff:
            kinds_by_text.setdefault(text, []).append(kind)

        assert "Apple" in kinds_by_text and "same" in kinds_by_text["Apple"]
        assert "Cherry" in kinds_by_text and "same" in kinds_by_text["Cherry"]
        assert "Banana" in kinds_by_text and "removed" in kinds_by_text["Banana"]
        assert "Blueberry" in kinds_by_text and "added" in kinds_by_text["Blueberry"]
        assert "Date" in kinds_by_text and "added" in kinds_by_text["Date"]

    def test_count_diff_lines(self):
        """count_diff_lines returns exact counts of added and removed lines."""
        old_text = "Line 1\nLine 2\nLine 3"
        new_text = "Line 1\nLine 2 modified\nLine 3\nLine 4"

        added, removed = count_diff_lines(old_text, new_text)
        assert added == 2  # 'Line 2 modified', 'Line 4'
        assert removed == 1  # 'Line 2'

    def test_identical_texts_produce_only_same(self):
        """Comparing identical texts produces 0 added and 0 removed lines."""
        text = "Hello\nWorld\nPageWatch"
        diff = text_diff_lines(text, text)
        assert all(kind == "same" for kind, _ in diff)

        added, removed = count_diff_lines(text, text)
        assert added == 0
        assert removed == 0

    def test_side_by_side_html_generates_table(self):
        """side_by_side_html produces an HTML table with diff classes."""
        old_text = "Item A\nItem B"
        new_text = "Item A\nItem C"

        html = side_by_side_html(old_text, new_text)
        assert isinstance(html, str)
        assert "<table" in html
        assert "diff_chg" in html
        assert "Item" in html


class TestSafeFileServing:
    """Tests for safe data file serving route and path traversal prevention."""

    @pytest.fixture
    def test_client(self, tmp_path, monkeypatch):
        """Create a Flask test client with an isolated data folder."""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        texts_dir = data_dir / "texts"
        texts_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(config, "DATA_DIR", str(data_dir))
        monkeypatch.setattr(config, "TEXT_DIR", str(texts_dir))

        # Create a legitimate file
        sample_file = texts_dir / "snapshot_1.txt"
        sample_file.write_text("Legitimate snapshot text content", encoding="utf-8")

        # Create a secret file OUTSIDE data folder to test traversal
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("CONFIDENTIAL PASSWORD", encoding="utf-8")

        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(bp)
        return app.test_client()

    def test_serve_legitimate_file_succeeds(self, test_client):
        """Legitimate file inside DATA_DIR returns HTTP 200 with content."""
        response = test_client.get("/data/texts/snapshot_1.txt")
        assert response.status_code == 200
        assert b"Legitimate snapshot text content" in response.data

    def test_path_traversal_is_blocked(self, test_client):
        """Attempts to traverse outside DATA_DIR with .. return HTTP 403 or 404."""
        response = test_client.get("/data/../secret.txt")
        assert response.status_code in (403, 404)
        assert b"CONFIDENTIAL" not in response.data

    def test_missing_file_returns_404(self, test_client):
        """Requesting a non-existent file inside DATA_DIR returns 404."""
        response = test_client.get("/data/texts/non_existent.txt")
        assert response.status_code == 404


class TestCompareRoute:
    """Tests for the /monitor/<id>/compare route."""

    @pytest.fixture
    def compare_app(self, tmp_path, monkeypatch):
        """Create clean test app with test database and sample snapshots."""
        from pagewatch import init
        from pagewatch.monitors_repo import create_monitor
        from pagewatch.db import run_write
        from PIL import Image, ImageDraw

        db_file = str(tmp_path / "compare_test.db")
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        texts_dir = data_dir / "texts"
        texts_dir.mkdir(parents=True, exist_ok=True)
        shots_dir = data_dir / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        diff_dir = data_dir / "diffs"
        diff_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(config, "DB_PATH", db_file)
        monkeypatch.setattr("pagewatch.db.DB_PATH", db_file)
        monkeypatch.setattr(config, "DATA_DIR", str(data_dir))
        monkeypatch.setattr(config, "TEXT_DIR", str(texts_dir))
        monkeypatch.setattr(config, "SCREENSHOT_DIR", str(shots_dir))
        monkeypatch.setattr(config, "DIFF_DIR", str(diff_dir))

        app = init(start_worker=False, start_scheduler_thread=False)
        app.config["TESTING"] = True

        # Create monitor
        mid = create_monitor({
            "name": "Test Site",
            "url": "http://127.0.0.1:5001/",
            "interval_minutes": 15,
        })

        # Create two sample snapshots with text and images
        txt1_path = str(texts_dir / f"{mid}_1.txt")
        with open(txt1_path, "w", encoding="utf-8") as f:
            f.write("Line 1: Hello\nLine 2: World")

        txt2_path = str(texts_dir / f"{mid}_2.txt")
        with open(txt2_path, "w", encoding="utf-8") as f:
            f.write("Line 1: Hello\nLine 2: World changed\nLine 3: New line")

        shot1_path = str(shots_dir / f"{mid}_1.png")
        img1 = Image.new("RGB", (100, 100), (255, 255, 255))
        img1.save(shot1_path)

        shot2_path = str(shots_dir / f"{mid}_2.png")
        img2 = Image.new("RGB", (100, 100), (255, 255, 255))
        draw = ImageDraw.Draw(img2)
        draw.rectangle([20, 20, 80, 80], fill=(0, 0, 255))
        img2.save(shot2_path)

        s1_id = run_write(
            "INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path, text_length) VALUES (?, '2026-10-16T10:00:00Z', 'hash1', ?, ?, 25)",
            (mid, txt1_path, shot1_path)
        )
        s2_id = run_write(
            "INSERT INTO snapshots (monitor_id, taken_at, content_hash, text_path, screenshot_path, text_length) VALUES (?, '2026-10-16T11:00:00Z', 'hash2', ?, ?, 45)",
            (mid, txt2_path, shot2_path)
        )

        return app.test_client(), mid, s1_id, s2_id

    def test_compare_two_snapshots_renders_all_sections(self, compare_app):
        """Comparing two valid snapshots renders diff metrics, unified diff, and side-by-side."""
        client, mid, s1_id, s2_id = compare_app
        res = client.get(f"/monitor/{mid}/compare?a={s1_id}&b={s2_id}")
        assert res.status_code == 200
        html = res.data.decode("utf-8")

        # Check section headings and metrics
        assert "Snapshot Comparison" in html
        assert "Unified Text Diff" in html
        assert "Side-by-Side Text Diff" in html
        assert "Highlighted Visual Diff" in html
        assert "Screenshots Side-by-Side" in html
        assert "lines" in html
        assert "visual change" in html

    def test_compare_same_snapshot_shows_friendly_message(self, compare_app):
        """Selecting the same snapshot for both dropdowns shows friendly error."""
        client, mid, s1_id, s2_id = compare_app
        res = client.get(f"/monitor/{mid}/compare?a={s1_id}&b={s1_id}")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "You selected the same snapshot" in html

    def test_compare_invalid_snapshot_id_rejected(self, compare_app):
        """Selecting snapshot from a different monitor shows error message."""
        client, mid, s1_id, s2_id = compare_app
        res = client.get(f"/monitor/{mid}/compare?a=9999&b={s2_id}")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Both selected snapshots must belong to monitor" in html

    def test_version_timeline_links_to_compare(self, compare_app):
        """Monitor timeline view shows diff summaries and links to compare."""
        client, mid, s1_id, s2_id = compare_app
        res = client.get(f"/monitor/{mid}")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Version Timeline" in html
        assert f"/monitors/{mid}/compare?a={s1_id}&amp;b={s2_id}" in html or f"/monitors/{mid}/compare" in html

