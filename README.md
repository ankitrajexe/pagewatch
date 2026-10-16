# PageWatch 🔍

> **A robust, self-hosted website change detector that monitors public web pages and alerts users to meaningful changes while filtering out noise.**

PageWatch renders pages in a headless Chromium browser (Playwright), extracts visible text and full screenshots, eliminates dynamic noise (timestamps, counters, ads, tokens), and detects meaningful updates using configurable sensitivity thresholds. It includes visual side-by-side diffs, multi-channel alerts (Email, Telegram, Discord), rate limiting, robots.txt compliance, numeric value tracking with Matplotlib charts, and per-page RSS 2.0 feeds.

---

## Table of Contents

1. [Overview & Screenshots Placeholder](#1-overview--screenshots)
2. [Setup & Run Instructions (Windows PowerShell)](#2-setup--run-instructions-windows-powershell)
3. [Architecture & Module Guide](#3-architecture--module-guide)
4. [Answers to Key Design Questions](#4-answers-to-key-design-questions)
5. [Latency, Behavior & Benchmark Results](#5-latency-behavior--benchmark-results)
6. [Failure Handling & Edge Cases](#6-failure-handling--edge-cases)
7. [5-Minute Live Demo Script](#7-5-minute-live-demo-script)
8. [Known Limitations](#8-known-limitations)
9. [How to Run Tests](#9-how-to-run-tests)

---

## 1. Overview & Screenshots

PageWatch operates as a lightweight, zero-JavaScript web application styled with Pico.css. It monitors web pages on intervals ranging from 15 minutes to 24 hours (with a 1-minute test mode for local demonstrations).

### Key Features
- **Headless Browser Rendering**: Uses Playwright Chromium sync API for full JavaScript single-page application (SPA) compatibility.
- **Smart Noise Filtering**: Automatically strips timestamps, view counters, ads, session tokens, and custom ignored CSS selectors before comparison.
- **1-Fetch Fan-Out**: Evaluates hundreds of monitors watching the same URL with only a single network fetch per cycle.
- **Visual & Text Diffs**: Unified diffs, side-by-side HTML comparisons, and Pillow-generated image diffs with red bounding boxes around changed regions.
- **Multi-Channel Alerts**: Instant notifications via SMTP Email, Telegram Bot, and Discord Webhooks with atomic deduplication.
- **Number Tracking & Charts**: Tracks prices and numerical metrics over time with server-rendered Matplotlib time-series charts.
- **Per-Page RSS 2.0 Feeds**: Hand-built XML feeds generated via standard library `xml.etree.ElementTree`.

### Screenshots Placeholder
- `[Screenshot Placeholder: Dashboard showing active monitors, check status dots, noise badges, and scheduler stats]`
- `[Screenshot Placeholder: Monitor Detail page with snapshot version timeline, number tracking chart, and RSS link]`
- `[Screenshot Placeholder: Side-by-side text comparison with highlighted additions (green) and deletions (red)]`
- `[Screenshot Placeholder: Visual screenshot diff with red bounding boxes surrounding changed content]`

---

## 2. Setup & Run Instructions (Windows PowerShell)

### Prerequisites
- Python 3.11 or newer installed on Windows.
- Windows PowerShell.

### Step-by-Step Setup

1. **Clone or Navigate to the Repository**:
   ```powershell
   cd "c:\DRIVE E\MY CHORES\vinnovateit\project 1\pagewatch"
   ```

2. **Create and Activate Virtual Environment**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

4. **Install Playwright Chromium Browser**:
   ```powershell
   playwright install chromium
   ```

5. **Configure Environment Variables**:
   Copy the example environment file:
   ```powershell
   Copy-Item .env.example .env
   ```
   *(Optional)* Edit `.env` to configure your SMTP credentials, Telegram bot token, or Discord webhook URL. By default, PageWatch operates safely without external alert credentials by logging notifications to standard output.

6. **Start the Local Test Site (Terminal 1)**:
   ```powershell
   python testsite/app.py
   ```
   *Runs on `http://127.0.0.1:5001/` with simulated price changes, live timestamps, rotating banners, and simulated errors.*

7. **Start PageWatch (Terminal 2)**:
   ```powershell
   # Optional: Enable fast 1-minute demo intervals
   $env:DEV_FAST_MODE = "true"
   python run.py
   ```
   *Runs on `http://127.0.0.1:5000/`. The background worker and APScheduler automatically initialize on startup.*

---

## 3. Architecture & Module Guide

### Architecture Flow

```
                      +-----------------------------+
                      |   Web UI (Flask/Pico.css)   |
                      |   - Dashboard & Add/Edit    |
                      |   - Snapshot Compare & RSS  |
                      +--------------+--------------+
                                     |
                          enqueues   | reads data
                                     v
                      +-----------------------------+
                      | SQLite (WAL Mode, DB_PATH)  |
                      | tables: urls, monitors,     |
                      | jobs, snapshots, check_log  |
                      +--------------+--------------+
                                     ^
                     scheduler ticks | claims due jobs
                                     |
  +-------------------------+        |        +-------------------------+
  |  APScheduler Scheduler  |--------+        |  Background Worker      |
  |  - Groups monitors      |                 |  (Single thread, owns   |
  |  - Enqueues 1 job / URL |                 |   Playwright Chromium)  |
  +-------------------------+                 +------------+------------+
                                                           |
                                    +----------------------+----------------------+
                                    |                      |                      |
                                    v                      v                      v
                          +-------------------+  +-------------------+  +-------------------+
                          |    ratelimit.py   |  |     fetcher.py    |  |    failures.py    |
                          |  - robots.txt     |  |  - Playwright     |  |  - Outages & 5xx  |
                          |  - 10s delay      |  |  - HTML/Text/PNG  |  |  - Bot/CAPTCHA    |
                          +-------------------+  +-------------------+  +-------------------+
                                                           |
                                                           v
                                                 +-------------------+
                                                 |     checker.py    |
                                                 |  - normalizer.py  |
                                                 |  - diff & hash    |
                                                 |  - save snapshot  |
                                                 +---------+---------+
                                                           |
                                                           v
                                                 +-------------------+
                                                 |     alerts.py     |
                                                 |  - Email, Telegram|
                                                 |  - Discord webhook|
                                                 +-------------------+
```

### Module Guide

| File | Purpose |
|---|---|
| `run.py` | Application entry point; calls `init()` and runs the Flask server on port 5000. |
| `pagewatch/__init__.py` | Central application factory: initializes SQLite schema, resets stuck jobs, and boots worker and scheduler threads. |
| `pagewatch/config.py` | Reads `.env` and defines operational defaults (timeouts, retries, directories, sensitivity). |
| `pagewatch/db.py` | SQLite connection manager with WAL mode, foreign key enforcement, and safe table migrations. |
| `pagewatch/fetcher.py` | Playwright sync wrapper: manages headless Chromium browser sessions and captures HTML, text, and PNG screenshots. |
| `pagewatch/jobqueue.py` | Atomic SQLite job queue (`jobs` table) with `BEGIN IMMEDIATE` transactions, exponential backoff retries, and stuck-job recovery. |
| `pagewatch/scheduler.py` | APScheduler background scheduler ticking every 30 seconds; groups due monitors by `url_id` to enqueue one job per URL. |
| `pagewatch/worker.py` | The single worker thread that owns Playwright, enforces polite delays and robots.txt, renders pages once, and fans out checks. |
| `pagewatch/ratelimit.py` | Enforces polite domain delays (10s default), caches `robots.txt` for 24 hours, and applies exponential backoff on HTTP 429/503. |
| `pagewatch/failures.py` | Classifies fetch results into `ok`, `error`, or `blocked` before content diffing to prevent false-positive change alerts. |
| `pagewatch/normalizer.py` | Strips scripts, ads, and noise (timestamps, counters, UUIDs) and calculates text similarity based on sensitivity thresholds. |
| `pagewatch/checker.py` | Core evaluation pipeline: extracts target regions, normalizes text, hashes with SHA-256, saves snapshots, and dispatches alerts. |
| `pagewatch/summary.py` | Deterministic, rule-based one-line change summarizer (price percentage changes, stock flips, keyword presence, new sections). |
| `pagewatch/differ.py` | Generates unified line diffs and safe side-by-side HTML comparison tables using Python's built-in `difflib`. |
| `pagewatch/imgdiff.py` | Visual screenshot differ using Pillow (`ImageChops`): pads dimensions, highlights changes with red boxes, and caches PNGs. |
| `pagewatch/alerts.py` | Multi-channel alert dispatcher (Email via SMTP, Telegram Bot, Discord Webhook) with atomic deduplication keys. |
| `pagewatch/digest.py` | Compiles 24-hour change summaries and dispatches daily digest digests at 09:00 UTC. |
| `pagewatch/numbers.py` | Extracts numbers across international formats, tracks time-series points, and renders Matplotlib charts with threshold lines. |
| `pagewatch/feeds.py` | Hand-built RSS 2.0 XML generator using Python's standard library `xml.etree.ElementTree`. |
| `pagewatch/web/routes.py` | Thin Flask routing blueprint for dashboard, monitor CRUD, manual "Check Now", comparison views, chart serving, and RSS. |
| `testsite/app.py` | Local standalone Flask test site running on port 5001 with controllable price, text, rotating banners, counters, and error endpoints. |

---

## 4. Answers to Key Design Questions

### 1. Is a site outage or CAPTCHA a change?
**Answer**: No. An outage (HTTP 500/502/504, timeout, connection/DNS failure) or CAPTCHA/Cloudflare challenge (HTTP 403/429/503 or bot-detection markers) is an operational failure, not a content update. PageWatch intercepts these during classification before comparing content hashes. It records the incident in `check_log` and updates the monitor's status to `error` or `blocked`, but **never** stores a snapshot or sends a "content changed" notification. Only after **3 consecutive failures** does PageWatch dispatch a dedicated "Site Down / Blocked" alert, followed by a "Site Recovered" notification once normal service resumes.  
*Implemented in: `pagewatch/failures.py:classify_fetch`, `pagewatch/worker.py:_process_job`, and `pagewatch/checker.py:check_monitor`.*

### 2. If 200 users watch the same URL, is it fetched 200 times?
**Answer**: No. PageWatch stores unique normalized URLs in the `urls` table, and monitors link to that single URL ID. The periodic scheduler groups all due monitors by `url_id` and enqueues exactly **one** job in the `jobs` table. The single worker thread renders the page once in Playwright, and then fans out the resulting HTML, text, and screenshot in memory to all 200 monitors. Each monitor evaluates its own include/ignore selectors, keywords, and sensitivity thresholds independently without performing redundant network requests.  
*Implemented in: `pagewatch/scheduler.py:scheduler_tick`, `pagewatch/jobqueue.py:enqueue_job`, `pagewatch/monitors_repo.py:get_or_create_url`, and `pagewatch/worker.py:_process_job`.*

### 3. How to avoid endless alerts on pages that differ on every load?
**Answer**: PageWatch applies three layers of defense:
1. **Noise Normalization**: Regular expressions replace dynamic timestamps, relative dates ("5 minutes ago"), view counters, session tokens, and hex UUIDs with static placeholders, while stripping built-in ad elements.
2. **Sensitivity Thresholds**: Minor line percentage shifts below the monitor's sensitivity threshold (`high`: any line; `medium`: >=2% lines; `low`: >=10% lines) are marked "unchanged" with message "below sensitivity" without creating a snapshot or alert.
3. **Endless-Change Guard**: If a page still registers changes across 5 consecutive checks, PageWatch marks the monitor with `is_noisy = 1`, pauses instant alerts, and displays a warning badge on the dashboard advising the user to add ignore selectors. The streak resets as soon as the page stabilizes.  
*Implemented in: `pagewatch/normalizer.py:normalize_text`, `pagewatch/normalizer.py:compare_texts`, `pagewatch/checker.py:check_monitor`, and `pagewatch/alerts.py:notify_change`.*

### 4. How to avoid hammering a site with requests?
**Answer**: PageWatch enforces four polite crawling mechanisms:
1. **Minimum Check Interval**: The UI dropdown and backend validation reject intervals shorter than 15 minutes (`MIN_INTERVAL_MINUTES = 15`).
2. **Per-Domain Delay**: The worker thread enforces a polite delay of at least 10 seconds (`DOMAIN_DELAY_SECONDS = 10`) between two consecutive requests to the same domain.
3. **Robots.txt Compliance**: `urllib.robotparser` fetches and caches `robots.txt` for 24 hours with an honest user agent (`PageWatchBot/1.0`), blocking checks if disallowed.
4. **Exponential Backoff**: When encountering HTTP 429 or 503, PageWatch reads the `Retry-After` header or doubles the domain's backoff interval up to 24 hours (`blocked_until`), adding random jitter (0–60 seconds) to check schedules.  
*Implemented in: `pagewatch/ratelimit.py:wait_for_domain`, `pagewatch/ratelimit.py:is_allowed_by_robots`, `pagewatch/ratelimit.py:apply_backoff`, and `pagewatch/scheduler.py:scheduler_tick`.*

---

## 5. Latency, Behavior & Benchmark Results

Real pipeline performance was measured against the local test website (`testsite/app.py`) using `scripts/measure.py`. The benchmark executed 20 checks of an unchanged page (containing live timestamps, rotating banners, and random tokens) followed by 5 checks with price changes.

### Measured Benchmark Data (`scripts/measure.py`)

| Metric | Measured Value | Notes |
|---|---|---|
| **Total Check Cycles** | **25 checks** | 20 unchanged checks + 5 changed checks |
| **Average Check Duration** | **637.5 ms** | Total time from Playwright fetch to DB commit |
| **Median Check Duration** | **634.6 ms** | Consistent headless render performance |
| **Minimum Check Duration** | **621.7 ms** | Fast unchanged check path |
| **Maximum Check Duration** | **665.8 ms** | Full snapshot write (text + PNG screenshot) |
| **Unchanged Check Average** | **632.2 ms** | Hash comparison match; 0 disk writes |
| **Changed Check Average** | **658.8 ms** | SHA-256 hash change; saved text + screenshot PNG |
| **Snapshots Stored for Monitor** | **6 snapshots** | 1 baseline + 5 changed; **0 snapshots for 20 unchanged checks** |
| **Fetches for 5 Shared Monitors** | **1 fetch** | 5 monitors evaluated in 789.3 ms total (1 single fetch) |

### Timeouts & Retries
- **Page Load Timeout**: 45 seconds (`PAGE_TIMEOUT_SECONDS`).
- **Worker Hard Guard**: Stuck jobs running for more than 5 minutes are automatically reset to `queued` on startup and every 30-second scheduler tick (`reset_stuck_jobs()`).
- **Retry Policy**: Failed jobs retry up to 3 attempts (`MAX_RETRIES`) with exponential backoff delays of 1, 2, and 4 minutes before reaching status `failed`.

---

## 6. Failure Handling & Edge Cases

| Failure Condition | Detection Trigger | Status Shown | Status Message | Snapshot Created? | Alert Dispatched? |
|---|---|---|---|---|---|
| **Site Outage (HTTP 500/502/504)** | HTTP status >= 400 | `ERROR` | `HTTP 500: Internal Server Error` | **No** | Only on 3 consecutive failures ("Site Down") |
| **Connection / DNS Failure** | Network exception in Playwright | `ERROR` | `Connection failed: net::ERR_NAME_NOT_RESOLVED` | **No** | Only on 3 consecutive failures ("Site Down") |
| **Page Timeout** | Exceeds 45s render threshold | `ERROR` | `Page load timed out after 45s` | **No** | Only on 3 consecutive failures ("Site Down") |
| **Bot Detection / CAPTCHA** | Text contains "verify you are human", "captcha", Cloudflare markers, or HTTP 403 | `BLOCKED` | `Access blocked: CAPTCHA or bot protection detected` | **No** | Only on 3 consecutive failures ("Site Blocked") |
| **Disallowed by robots.txt** | `robots.txt` forbids `PageWatchBot/1.0` | `BLOCKED` | `Blocked by robots.txt` | **No** | Only on 3 consecutive failures ("Site Blocked") |
| **Empty Page / Blank Render** | Visible text length < 20 chars | `ERROR` | `Page returned empty or unrenderable content` | **No** | Only on 3 consecutive failures ("Site Down") |
| **Selector Matches Nothing** | Element not found for CSS selector | `OK` | Content extracted as empty string; falls back safely | **No** | No alert |
| **Noisy Page (Flaps every load)** | 5 consecutive checks register changes | `OK` (with ⚠️ badge) | `Page changes every load. Add ignore selectors.` | Yes | **Paused** (endless-alert guard prevents notification spam) |

---

## 7. 5-Minute Live Demo Script

Use this step-by-step walkthrough to demonstrate PageWatch's core features in under 5 minutes:

1. **Start the Test Site**:
   ```powershell
   python testsite/app.py
   ```
   *Runs on port 5001.*

2. **Start PageWatch in Fast Demo Mode**:
   ```powershell
   $env:DEV_FAST_MODE = "true"
   python run.py
   ```
   *Runs on port 5000 with 1-minute intervals allowed.*

3. **Open the Dashboard**:
   - Navigate to `http://localhost:5000/`.
   - Show the clean Pico.css dashboard and the scheduler status footer (Scheduler Running: YES).

4. **Create a Monitor**:
   - Click **Add Monitor**.
   - Fill in:
     - **Name**: `Widget Store`
     - **URL**: `http://127.0.0.1:5001/`
     - **Check Interval**: `1 minute`
     - **Sensitivity**: `Medium`
     - **Number Selector**: `.price` *(inside Keyword & Number Tracking)*
     - **Alert Email**: `demo@example.com`
   - Click **Create Monitor**.

5. **Show Baseline Snapshot**:
   - PageWatch redirects to the Dashboard. The monitor displays status `OK` with Snapshot #1 captured as the baseline.
   - Click on `Widget Store` to view the **Version Timeline** and the **Number Tracking Chart**.

6. **Demonstrate Noise Filtering**:
   - Click **Check Now**.
   - The check completes in ~630 ms. The status outcome is **Unchanged**, and no duplicate snapshot is created despite the rotating banner, live clock, and view counter changing on every single load!

7. **Simulate a Real Price Drop**:
   - In a second browser tab, navigate to `http://127.0.0.1:5001/set-price/399` to lower the price from $499 to $399.
   - Return to PageWatch and click **Check Now**.
   - Snapshot #2 is created instantly! The timeline displays:  
     `📝 Price dropped from 499 to 399 (-20.0%)`

8. **Inspect Comparisons & Diffs**:
   - Click **Compare Any Two Versions**.
   - Show the green/red unified text diff, the side-by-side HTML view, and the visual screenshot diff displaying a red bounding box around the updated price.

9. **View the Live RSS Feed & Trend Chart**:
   - Click the **RSS Feed** button in the header or visit `http://localhost:5000/monitors/1/feed.xml` to show the standard RSS 2.0 XML feed with direct compare links.
   - View the updated Matplotlib line chart on the monitor page showing the price point dropping from $499 to $399.

10. **Demonstrate Failure & CAPTCHA Resilience**:
    - Add a second monitor pointing to `http://127.0.0.1:5001/captcha`.
    - Click **Check Now**.
    - Notice status changes to `BLOCKED` with message `Access blocked: CAPTCHA or bot protection detected`. No snapshot is stored and no false change notification is sent!

---

## 8. Known Limitations

- **Single Worker Thread**: Playwright sync API objects must remain in the thread that created them. While PageWatch's single-thread model easily handles hundreds of monitors on 15m–24h intervals, high-throughput commercial enterprise scale (>10,000 checks/hour) would benefit from multi-worker process pools or distributed Celery queues.
- **SQLite Database**: PageWatch uses SQLite with Write-Ahead Logging (WAL) and busy timeouts. It is fast, self-contained, and requires zero setup, but cannot run across multi-node server clusters.
- **No User Login / Multi-Tenancy**: Designed as a private self-hosted utility. All monitors and alert configurations are visible to anyone with access to the web interface.
- **Browser Memory Overhead**: Headless Chromium provides complete JavaScript single-page application support, but uses more memory (~150 MB) than raw HTTP GET requests.

---

## 9. How to Run Tests

PageWatch includes 171 automated unit and integration tests covering the normalizer, job queue, rate limiter, failures, alerts, diffing, numbers, feeds, and web routes.

Run the entire test suite using `pytest`:

```powershell
.\venv\Scripts\python.exe -m pytest -v
```

### Expected Output
```
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.7.0
rootdir: C:\DRIVE E\MY CHORES\vinnovateit\project 1\pagewatch
collected 171 items

tests\test_alerts.py .......................                             [ 13%]
tests\test_checker.py .......                                            [ 17%]
tests\test_differ.py ...........                                         [ 23%]
tests\test_failures.py ............                                      [ 30%]
tests\test_feeds.py .......                                              [ 35%]
tests\test_imgdiff.py ....                                               [ 37%]
tests\test_jobqueue.py ....                                              [ 39%]
tests\test_monitors_web.py .........                                     [ 45%]
tests\test_normalizer.py .............................                   [ 61%]
tests\test_numbers.py .................                                  [ 71%]
tests\test_ratelimit.py .........                                        [ 77%]
tests\test_scheduler.py ..........                                       [ 83%]
tests\test_summary.py ..............                                     [ 91%]
tests\test_urlutils.py ...............                                   [100%]

============================= 171 passed in 7.10s =============================
```

To run a specific test suite:
```powershell
.\venv\Scripts\python.exe -m pytest tests/test_normalizer.py -v
.\venv\Scripts\python.exe -m pytest tests/test_summary.py -v
.\venv\Scripts\python.exe -m pytest tests/test_numbers.py -v
.\venv\Scripts\python.exe -m pytest tests/test_feeds.py -v
```
