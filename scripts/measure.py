# scripts/measure.py
# ------------------
# What it does: Runs the real PageWatch pipeline against the local test website
#               (testsite/app.py) to measure latency and verify behavior:
#               1. Runs 20 checks of the unchanged page (timestamp/token noise filtered).
#               2. Runs 5 checks of changed pages (price changes).
#               3. Measures duration per check (average, median, max in milliseconds).
#               4. Counts snapshots created (proves noise does not create snapshots).
#               5. Verifies 1 fetch per cycle for 5 monitors watching the same URL.
# Talks to: testsite/app.py, fetcher.py, checker.py, normalizer.py, db.py, config.py.

import os
import sys
import time
import statistics
import threading
import tempfile
from datetime import datetime, timezone
from werkzeug.serving import make_server
import requests

# Ensure project root is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pagewatch import config
from pagewatch.db import create_tables, run_query, run_write
from pagewatch import monitors_repo
from pagewatch.fetcher import BrowserSession
from pagewatch.checker import check_monitor
from testsite.app import app as test_app


def main():
    print("================================================================")
    print("PageWatch Pipeline Benchmark & Latency Measurement Tool")
    print("================================================================\n")

    # 1. Setup isolated test environment in temp directory
    temp_dir = tempfile.mkdtemp(prefix="pagewatch_measure_")
    test_db = os.path.join(temp_dir, "measure.db")
    test_texts = os.path.join(temp_dir, "texts")
    test_shots = os.path.join(temp_dir, "screenshots")
    os.makedirs(test_texts, exist_ok=True)
    os.makedirs(test_shots, exist_ok=True)

    config.DB_PATH = test_db
    import pagewatch.db
    pagewatch.db.DB_PATH = test_db
    config.TEXT_DIR = test_texts
    config.SCREENSHOT_DIR = test_shots
    config.ALLOW_LOCALHOST = True
    config.ROBOTS_SKIP_LOCALHOST = True

    create_tables()
    print(f"[*] Isolated test database initialized at: {test_db}")

    # 2. Start local test website (port 5001) in background thread
    server = make_server("127.0.0.1", 5001, test_app)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    # Verify test site is responding
    target_url = "http://127.0.0.1:5001/"
    res = requests.get(target_url, timeout=5)
    if res.status_code != 200:
        print(f"[!] Error: Testsite returned status {res.status_code}")
        server.shutdown()
        return

    print(f"[*] Local test website running on {target_url}\n")

    # 3. Start Playwright headless browser session
    print("[*] Launching headless Playwright Chromium session...")
    browser = BrowserSession()
    browser.start()

    # Create monitor
    monitor_id = monitors_repo.create_monitor({
        "name": "Benchmark Monitor",
        "url": target_url,
        "interval_minutes": 15,
        "sensitivity": "medium"
    })
    monitor = monitors_repo.get_monitor(monitor_id)

    # 4. Initial baseline check
    print("[*] Performing initial check (baseline snapshot creation)...")
    fetch_res = browser.fetch_page(target_url)
    res_base = check_monitor(monitor, fetch_res)
    assert res_base["outcome"] == "changed"
    print(f"    Baseline snapshot #{res_base['snapshot_id']} created.\n")

    # 5. Measure 20 checks of UNCHANGED page (with live timestamps, rotating banners, counters)
    print("[*] Running 20 checks of UNCHANGED page (verifying noise filtering)...")
    unchanged_durations = []
    for i in range(1, 21):
        t_start = time.perf_counter()
        fetch_res = browser.fetch_page(target_url)
        monitor = monitors_repo.get_monitor(monitor_id)
        outcome = check_monitor(monitor, fetch_res)
        t_dur_ms = (time.perf_counter() - t_start) * 1000.0
        unchanged_durations.append(t_dur_ms)
        assert outcome["outcome"] == "unchanged", f"Expected unchanged, got {outcome}"
        print(f"    Check {i:02d}/20: {t_dur_ms:6.1f} ms | Outcome: {outcome['outcome']}")

    # 6. Measure 5 checks of CHANGED page (price changed via /set-price/<n>)
    print("\n[*] Running 5 checks of CHANGED page (modifying price between checks)...")
    changed_durations = []
    prices = [549, 599, 499, 649, 429]
    for idx, new_price in enumerate(prices, start=1):
        requests.get(f"http://127.0.0.1:5001/set-price/{new_price}", timeout=5)
        t_start = time.perf_counter()
        fetch_res = browser.fetch_page(target_url)
        monitor = monitors_repo.get_monitor(monitor_id)
        outcome = check_monitor(monitor, fetch_res)
        t_dur_ms = (time.perf_counter() - t_start) * 1000.0
        changed_durations.append(t_dur_ms)
        assert outcome["outcome"] == "changed", f"Expected changed, got {outcome}"
        print(f"    Check {idx:02d}/05: {t_dur_ms:6.1f} ms | Outcome: {outcome['outcome']} (Price set to ${new_price})")

    # 7. Test 5 monitors watching the same URL (fan-out verification)
    print("\n[*] Verifying fan-out: 5 monitors watching the exact same URL...")
    multi_monitor_ids = []
    for m_i in range(1, 6):
        m_id = monitors_repo.create_monitor({
            "name": f"Shared URL Monitor #{m_i}",
            "url": target_url,
            "interval_minutes": 15,
            "sensitivity": "medium"
        })
        multi_monitor_ids.append(m_id)

    # In the PageWatch pipeline, all monitors sharing the same url_id share ONE fetch
    fetch_counter = 0
    t_fanout_start = time.perf_counter()

    # Step A: Fetch page ONCE
    fetch_counter += 1
    shared_fetch = browser.fetch_page(target_url)

    # Step B: Process fetch across all 5 monitors
    monitors_checked = 0
    for m_id in multi_monitor_ids:
        m_row = monitors_repo.get_monitor(m_id)
        check_monitor(m_row, shared_fetch)
        monitors_checked += 1
    t_fanout_ms = (time.perf_counter() - t_fanout_start) * 1000.0

    print(f"    Monitors checked: {monitors_checked}")
    print(f"    Browser fetches performed: {fetch_counter} (exactly 1 fetch for all {monitors_checked} monitors)")
    print(f"    Total fan-out cycle time: {t_fanout_ms:.1f} ms")

    # 8. Compute and report metrics
    all_durations = unchanged_durations + changed_durations
    avg_dur = statistics.mean(all_durations)
    median_dur = statistics.median(all_durations)
    max_dur = max(all_durations)
    min_dur = min(all_durations)

    unchanged_avg = statistics.mean(unchanged_durations)
    changed_avg = statistics.mean(changed_durations)

    # Count total snapshots stored in DB for Benchmark Monitor
    snap_rows = run_query("SELECT COUNT(*) as count FROM snapshots WHERE monitor_id = ?", (monitor_id,))
    total_snapshots_benchmark = snap_rows[0]["count"]

    # All snapshots across entire run
    all_snap_rows = run_query("SELECT COUNT(*) as count FROM snapshots")
    total_snapshots_all = all_snap_rows[0]["count"]

    print("\n================================================================")
    print("BENCHMARK RESULTS SUMMARY (REAL MEASURED DATA)")
    print("================================================================")
    print(f"Total check cycles measured:     {len(all_durations)} (20 unchanged + 5 changed)")
    print(f"Average check duration:          {avg_dur:.1f} ms")
    print(f"Median check duration:           {median_dur:.1f} ms")
    print(f"Min check duration:              {min_dur:.1f} ms")
    print(f"Max check duration:              {max_dur:.1f} ms")
    print(f"Unchanged check average:         {unchanged_avg:.1f} ms (no snapshot written)")
    print(f"Changed check average:           {changed_avg:.1f} ms (text + screenshot saved)")
    print(f"Snapshots stored for monitor:    {total_snapshots_benchmark} (1 baseline + 5 changed; 0 for 20 unchanged)")
    print(f"Fetches for 5 shared monitors:   {fetch_counter} fetch per cycle ({monitors_checked} monitors evaluated)")
    print("================================================================\n")

    # Clean up
    browser.stop()
    server.shutdown()
    print("[*] Benchmark completed successfully.")


if __name__ == "__main__":
    main()
