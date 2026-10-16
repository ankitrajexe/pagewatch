# test_picker.py
# --------------
# What it does: Unit and integration tests for the visual region picker.
#               Tests CSS selector generation on HTML strings (with ID, without ID,
#               data attributes, classes, nth-of-type), monitor selector updates,
#               and picker web routes.

import os
import json
import pytest
from bs4 import BeautifulSoup

from pagewatch import config
from pagewatch.db import get_connection, run_query, run_write
from pagewatch.picker import (
    generate_css_selector,
    add_selector_to_monitor,
    remove_selector_from_monitor,
)
from pagewatch.jobqueue import enqueue_job


# ---------------------------------------------------------------------------
# Unit tests for generate_css_selector
# ---------------------------------------------------------------------------

def test_generate_selector_with_id():
    """
    Test that an element with a valid unique ID returns '#id'.
    """
    html = """
    <html>
        <body>
            <div id="main-content">
                <h1 id="page-title">Page Title</h1>
                <div id="product-price">$99.99</div>
            </div>
        </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    price_el = soup.find(id="product-price")

    selector = generate_css_selector(soup, price_el)
    assert selector == "#product-price"

    # Verify that the selector uniquely targets this element in the document
    matches = soup.select(selector)
    assert len(matches) == 1
    assert matches[0] == price_el


def test_generate_selector_without_id_using_data_attribute():
    """
    Test that an element without an ID but with a unique data-* attribute
    generates a clean attribute selector.
    """
    html = """
    <div class="product">
        <span data-testid="stock-badge">In Stock</span>
        <span>Other Info</span>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    badge_el = soup.find(attrs={"data-testid": "stock-badge"})

    selector = generate_css_selector(soup, badge_el)
    assert selector == 'span[data-testid="stock-badge"]'

    matches = soup.select(selector)
    assert len(matches) == 1
    assert matches[0] == badge_el


def test_generate_selector_without_id_using_class():
    """
    Test that an element without an ID or data attribute uses its class name.
    """
    html = """
    <section>
        <div class="summary-box">Summary text</div>
        <div class="footer-box">Footer text</div>
    </section>
    """
    soup = BeautifulSoup(html, "html.parser")
    target = soup.find(class_="summary-box")

    selector = generate_css_selector(soup, target)
    assert selector == "div.summary-box"

    matches = soup.select(selector)
    assert len(matches) == 1
    assert matches[0] == target


def test_generate_selector_without_id_using_nth_of_type():
    """
    Test that an element without ID, data attributes, or unique classes
    falls back to a hierarchical path with :nth-of-type(n).
    """
    html = """
    <div id="container">
        <ul>
            <li>Item One</li>
            <li>Item Two</li>
            <li>Item Three</li>
        </ul>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    items = soup.find_all("li")
    second_item = items[1]

    selector = generate_css_selector(soup, second_item)
    assert "li:nth-of-type(2)" in selector

    # Verify the selector uniquely matches the second item
    matches = soup.select(selector)
    assert len(matches) == 1
    assert matches[0] == second_item


def test_generate_selector_nested_structure():
    """
    Test hierarchical selector generation on a nested page structure without IDs.
    """
    html = """
    <main>
        <article>
            <p>Intro paragraph</p>
            <p>Second paragraph</p>
        </article>
    </main>
    """
    soup = BeautifulSoup(html, "html.parser")
    paragraphs = soup.find_all("p")
    second_p = paragraphs[1]

    selector = generate_css_selector(soup, second_p)
    matches = soup.select(selector)
    assert len(matches) == 1
    assert matches[0] == second_p


# ---------------------------------------------------------------------------
# Database selector update tests
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_monitor(tmp_path):
    """Create a sample URL and monitor in the test database."""
    from pagewatch.monitors_repo import create_monitor
    monitor_id = create_monitor({
        "name": "Picker Test Monitor",
        "url": "http://127.0.0.1:8000/product",
        "interval_minutes": 15,
        "sensitivity": "medium",
        "include_selectors": "#initial-include",
        "ignore_selectors": "#initial-ignore",
    })
    yield monitor_id

    # Cleanup
    run_write("DELETE FROM jobs WHERE monitor_id = ?", (monitor_id,))
    run_write("DELETE FROM monitors WHERE id = ?", (monitor_id,))


def test_add_and_remove_selectors(sample_monitor):
    """
    Test adding and removing include/ignore selectors for a monitor.
    """
    m_id = sample_monitor

    # 1. Add a new include selector
    ok = add_selector_to_monitor(m_id, "include", ".price-card")
    assert ok is True

    # Duplicate add should not duplicate lines
    add_selector_to_monitor(m_id, "include", ".price-card")

    rows = run_query("SELECT include_selectors FROM monitors WHERE id = ?", (m_id,))
    lines = [l.strip() for l in rows[0]["include_selectors"].splitlines() if l.strip()]
    assert "#initial-include" in lines
    assert ".price-card" in lines
    assert lines.count(".price-card") == 1

    # 2. Add an ignore selector
    add_selector_to_monitor(m_id, "ignore", ".cookie-banner")
    rows = run_query("SELECT ignore_selectors FROM monitors WHERE id = ?", (m_id,))
    lines = [l.strip() for l in rows[0]["ignore_selectors"].splitlines() if l.strip()]
    assert ".cookie-banner" in lines

    # 3. Remove selectors
    remove_selector_from_monitor(m_id, "include", ".price-card")
    rows = run_query("SELECT include_selectors FROM monitors WHERE id = ?", (m_id,))
    assert ".price-card" not in rows[0]["include_selectors"]
    assert "#initial-include" in rows[0]["include_selectors"]

    remove_selector_from_monitor(m_id, "ignore", ".cookie-banner")
    rows = run_query("SELECT ignore_selectors FROM monitors WHERE id = ?", (m_id,))
    assert ".cookie-banner" not in rows[0]["ignore_selectors"]


# ---------------------------------------------------------------------------
# Web route integration tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Create Flask test client."""
    from pagewatch import init
    app = init(start_worker=False, start_scheduler_thread=False)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_picker_loading_page_when_not_ready(client, sample_monitor):
    """
    When picker files do not exist yet on disk, visiting /monitors/<id>/picker
    must enqueue a 'picker_snapshot' job and render the loading page with meta refresh.
    """
    m_id = sample_monitor
    png_path = os.path.join(config.PICKER_DIR, f"monitor_{m_id}.png")
    json_path = os.path.join(config.PICKER_DIR, f"monitor_{m_id}.json")

    # Ensure no old files exist
    for p in (png_path, json_path):
        if os.path.isfile(p):
            os.remove(p)

    resp = client.get(f"/monitors/{m_id}/picker")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    # Must contain meta refresh tag and friendly loading message
    assert '<meta http-equiv="refresh" content="3">' in html
    assert "Preparing page preview..." in html

    # Verify a picker_snapshot job was enqueued in the database
    jobs = run_query(
        "SELECT * FROM jobs WHERE monitor_id = ? AND job_type = 'picker_snapshot'",
        (m_id,)
    )
    assert len(jobs) >= 1
    assert jobs[0]["status"] in ("queued", "running")


def test_picker_ready_page(client, sample_monitor):
    """
    When picker PNG and JSON files exist on disk, visiting /monitors/<id>/picker
    must render picker.html with overlays and current selector lists.
    """
    m_id = sample_monitor
    png_path = os.path.join(config.PICKER_DIR, f"monitor_{m_id}.png")
    json_path = os.path.join(config.PICKER_DIR, f"monitor_{m_id}.json")

    # Create dummy PNG file
    from PIL import Image
    img = Image.new("RGB", (1280, 800), color="white")
    img.save(png_path)

    # Create dummy JSON file with sample element
    data = {
        "monitor_id": m_id,
        "image_width": 1280,
        "image_height": 800,
        "elements": [
            {
                "selector": "#sample-title",
                "tag": "h1",
                "x": 50,
                "y": 100,
                "w": 300,
                "h": 40
            }
        ]
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    try:
        resp = client.get(f"/monitors/{m_id}/picker")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        assert "Visual Region Picker" in html
        assert 'data-selector="#sample-title"' in html
        assert "Watch this region" in html
        assert "Ignore this region" in html
        assert "#initial-include" in html
        assert "#initial-ignore" in html
    finally:
        # Cleanup test files
        if os.path.isfile(png_path):
            os.remove(png_path)
        if os.path.isfile(json_path):
            os.remove(json_path)


def test_picker_add_and_remove_routes(client, sample_monitor):
    """
    Test POST /monitors/<id>/picker/add and /remove endpoints.
    """
    m_id = sample_monitor

    # Add include selector
    resp = client.post(
        f"/monitors/{m_id}/picker/add",
        data={"selector_type": "include", "selector": "#new-price-box"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/picker")

    rows = run_query("SELECT include_selectors FROM monitors WHERE id = ?", (m_id,))
    assert "#new-price-box" in rows[0]["include_selectors"]

    # Remove include selector
    resp = client.post(
        f"/monitors/{m_id}/picker/remove",
        data={"selector_type": "include", "selector": "#new-price-box"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    rows = run_query("SELECT include_selectors FROM monitors WHERE id = ?", (m_id,))
    assert "#new-price-box" not in rows[0]["include_selectors"]


def test_picker_refresh_route(client, sample_monitor):
    """
    Test POST /monitors/<id>/picker/refresh deletes old files and enqueues a new job.
    """
    m_id = sample_monitor
    png_path = os.path.join(config.PICKER_DIR, f"monitor_{m_id}.png")
    json_path = os.path.join(config.PICKER_DIR, f"monitor_{m_id}.json")

    # Create dummy files
    with open(png_path, "wb") as f:
        f.write(b"fake png")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write("{}")

    resp = client.post(f"/monitors/{m_id}/picker/refresh", follow_redirects=False)
    assert resp.status_code == 302

    # Files should have been cleared
    assert not os.path.isfile(png_path)
    assert not os.path.isfile(json_path)

    # Job should be queued
    jobs = run_query(
        "SELECT * FROM jobs WHERE monitor_id = ? AND job_type = 'picker_snapshot' AND status = 'queued'",
        (m_id,)
    )
    assert len(jobs) >= 1


def test_capture_picker_snapshot_with_playwright(tmp_path):
    """
    Test real Playwright extraction of elements and full-page screenshot.
    """
    from pagewatch.fetcher import BrowserSession
    from pagewatch.picker import capture_picker_snapshot

    session = BrowserSession()
    session.start()
    try:
        html_content = """
        <!DOCTYPE html>
        <html>
        <head><title>Test Store</title></head>
        <body style="margin: 0; padding: 20px; font-family: sans-serif;">
            <header id="header" style="height: 60px; background: #eee;">
                <h1 id="brand-title">Acme Widgets</h1>
            </header>
            <main id="main-content" style="padding: 20px;">
                <div class="product-card" style="width: 300px; padding: 15px; border: 1px solid #ccc;">
                    <h2 class="product-name">Super Widget</h2>
                    <span data-price="49" class="price-tag" style="display: inline-block; font-size: 20px;">$49.99</span>
                    <button id="buy-btn" style="display: block; margin-top: 10px; width: 100px; height: 30px;">Buy</button>
                </div>
            </main>
        </body>
        </html>
        """
        temp_html_file = str(tmp_path / "page.html")
        with open(temp_html_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        file_url = f"file:///{os.path.abspath(temp_html_file).replace(os.sep, '/')}"
        out_png = str(tmp_path / "picker.png")
        out_json = str(tmp_path / "picker.json")

        result = capture_picker_snapshot(
            session,
            file_url,
            monitor_id=999,
            out_png_path=out_png,
            out_json_path=out_json,
        )

        assert os.path.isfile(out_png)
        assert os.path.isfile(out_json)
        assert os.path.getsize(out_png) > 0

        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["monitor_id"] == 999
        assert len(data["elements"]) > 0

        # Check that selectors were found
        selectors = [el["selector"] for el in data["elements"]]
        assert any("#brand-title" in s or "#header" in s or "#buy-btn" in s for s in selectors)
        assert any("product-card" in s or "product-name" in s or "price-tag" in s or "data-price" in s for s in selectors)

        # Check bounding box coordinates
        for el in data["elements"]:
            assert el["w"] > 0
            assert el["h"] > 0
            assert el["x"] >= 0
            assert el["y"] >= 0
    finally:
        session.stop()

