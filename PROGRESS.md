# PROGRESS.md

## Step 1: Project Skeleton, Config & Database Layer ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

- **Folder structure** — all directories created: `pagewatch/`, `pagewatch/web/templates/`, `testsite/`, `tests/`, `data/screenshots/`, `data/texts/`
- **`pagewatch/config.py`** — loads `.env` with python-dotenv, defines all constants with defaults (DATA_DIR, DB_PATH, SCREENSHOT_DIR, TEXT_DIR, MIN/MAX intervals, timeouts, retries, SMTP settings, Telegram token, BASE_URL). Auto-creates data folders.
- **`pagewatch/db.py`** — `get_connection()` (SQLite with WAL mode, foreign keys, dict-like rows), `create_tables()` (all 7 tables: urls, monitors, snapshots, jobs, check_log, alerts, number_points), `run_query()` and `run_write()` helpers.
- **`pagewatch/__init__.py`** — `init()` function: creates tables → creates Flask app → registers routes blueprint → returns app. Has placeholder comments for future steps.
- **`pagewatch/web/routes.py`** — one route `"/"` rendering dashboard with monitor count from DB.
- **`pagewatch/web/templates/base.html`** — Pico.css from CDN, nav bar with Dashboard and Add Monitor links.
- **`pagewatch/web/templates/dashboard.html`** — shows "PageWatch is running" and monitor count (currently 0).
- **`run.py`** — entry point, calls `init()`, runs on port 5000 with `debug=False`.
- **`.env.example`** — all config keys with no real secrets.

### Files created

| File | Purpose |
|---|---|
| `run.py` | App entry point |
| `pagewatch/__init__.py` | App factory |
| `pagewatch/config.py` | Configuration loader |
| `pagewatch/db.py` | Database layer |
| `pagewatch/web/routes.py` | Flask routes |
| `pagewatch/web/templates/base.html` | HTML base layout |
| `pagewatch/web/templates/dashboard.html` | Dashboard page |
| `.env.example` | Config template |

### Tested

- All 7 database tables created successfully.
- Flask server starts on port 5000.
- `GET /` returns 200 with "PageWatch is running" and "Monitors in database: 0".

### Known issues

- None.

### What's next

- ~~Step 2~~ ✅
- Step 3 and beyond per PLAN.md

---

## Step 2: Fetcher & Test Site ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

- **`pagewatch/fetcher.py`** — `BrowserSession` class with `start()`, `stop()`, `fetch_page()`. Uses Playwright sync API, headless Chromium. Each fetch creates a fresh browser context (clean cookies). Returns a plain dict with `ok`, `http_status`, `final_url`, `html`, `page_text`, `screenshot_bytes`, `error_type`, `error_message`, `duration_ms`. All errors caught internally — never raises exceptions.
- **`testsite/app.py`** — Flask test site on port 5001 with routes:
  - `/` — product page with price, timestamp, rotating banner, random token, view counter, stable text
  - `/set-price/<n>` and `/set-text/<words>` — change price/text
  - `/captcha` — fake bot-detection page
  - `/down` — HTTP 500
  - `/slow` — 60-second sleep (timeout testing)
  - `/always-different` — random content every load
- **`scripts/try_fetch.py`** — CLI tool to test the fetcher. Takes a URL, prints results, saves screenshot.

### Files created

| File | Purpose |
|---|---|
| `pagewatch/fetcher.py` | Playwright page fetcher |
| `testsite/app.py` | Local test website (port 5001) |
| `scripts/try_fetch.py` | Manual fetch test script |

### Tested

| Test | Result |
|---|---|
| Fetch product page (`/`) | ✅ OK, status 200, text + screenshot captured, ~2000 ms |
| Fetch captcha page (`/captcha`) | ✅ OK, status 200, text says "Please verify you are human" |
| Fetch error page (`/down`) | ✅ OK (fetched), status 500, text "Internal Server Error" |
| Fetch always-different (`/always-different`) | ✅ OK, random content returned |
| Fetch slow page (`/slow`, timeout=3s) | ✅ Caught as `error_type=timeout`, no crash, ~3100 ms |
| Fetch non-existent domain | ✅ Caught as `error_type=dns`, no crash |

### Known issues

- None.

### What's next

- ~~Step 3~~ ✅
- Step 4 and beyond per PLAN.md

---

## Step 3: Normalizer & Pure Logic Tests ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

- **`pagewatch/normalizer.py`** — Pure data transformation and comparison functions:
  - `normalize_text(raw_text)`: Regex noise replacement for ISO dates, DMY dates, named dates, times, relative times ("5 minutes ago"), updated notices, counters ("1,234 views"), UUIDs, hex and base64 tokens. Collapses whitespace and removes empty lines.
  - `hash_text(text)`: Computes SHA-256 hexadecimal hash string.
  - `compare_texts(old_text, new_text, sensitivity)`: Compares two texts line-by-line using `difflib`. Computes percentage change and determines whether change is meaningful under `high` (any change), `medium` (>=2% change or >=1 line if text < 50 lines), and `low` (>=10% change) sensitivity.
  - `extract_text_from_html(html, include_selectors, ignore_selectors)`: Parses HTML with BeautifulSoup4 + lxml. Strips script/style/noscript/iframe/svg tags, removes built-in ad elements (`AD_SELECTORS`), drops custom ignored selectors, extracts text from included CSS selectors (or full page if empty). Gracefully catches invalid selectors without crashing and reports them.
  - `parse_selector_lines(text)`: Parses newline-delimited CSS selector strings.
- **`pagewatch/config.py`** — Added sensitivity threshold constants (`SENSITIVITY_HIGH_PERCENT`, `SENSITIVITY_MEDIUM_PERCENT`, `SENSITIVITY_LOW_PERCENT`, `SHORT_TEXT_LINE_THRESHOLD`, `NOISY_STREAK_LIMIT`).
- **`requirements.txt`** — Added `beautifulsoup4`, `lxml`, and `soupsieve`.
- **`tests/test_normalizer.py`** — 29 comprehensive pytest unit tests covering noise replacement, hashing consistency, sensitivity thresholds, HTML extraction, ad removal, region inclusion/exclusion, and error resilience.
- **`conftest.py`** — Configured root project directory on `sys.path` for frictionless `pytest` execution.

### Files created / modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/normalizer.py` | Created | Noise filtering, hashing, and sensitivity comparison |
| `tests/test_normalizer.py` | Created | 29 unit tests covering all normalizer behaviors |
| `conftest.py` | Created | Pytest path resolution helper |
| `pagewatch/config.py` | Modified | Added sensitivity thresholds |
| `requirements.txt` | Modified | Added beautifulsoup4 and lxml |

### Tested

- Ran `venv\Scripts\pytest.exe -v` (and `python -m pytest -v`):
  - **29 passed in 0.21s**
  - Verified timestamp and counter replacement
  - Verified identical hashes when only timestamps vary
  - Verified different hashes when price/content changes
  - Verified high, medium, and low sensitivity thresholds
  - Verified selector include, ignore, and bad selector safety

### Known issues

- None.

### What's next

- ~~Step 4~~ ✅
- Step 5 and beyond per PLAN.md

---

## Step 4: Web UI for Monitor CRUD & URL Normalization ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

- **`pagewatch/urlutils.py`** — URL validation and normalization:
  - `normalize_url(url)`: Lowercases scheme/host, strips fragments, strips trailing slashes, enforces `http`/`https` protocols, checks localhost permission against `config.ALLOW_LOCALHOST`.
  - `get_domain(url)`: Extracts lowercase domain name from URLs.
- **`pagewatch/monitors_repo.py`** — Database repository layer for monitors:
  - `get_or_create_url(url)`: Implements PLAN.md 5.2 requirement ensuring multiple monitors watching the same URL share one row in `urls`.
  - `create_monitor(data)`: Inserts monitor with initial status `pending` and `next_check_at = now`.
  - `list_monitors()`: Queries active monitors joined with URL and domain, newest first.
  - `get_monitor(monitor_id)`: Fetches single monitor joined with URL info.
  - `update_monitor(monitor_id, data)`: Updates monitor settings and re-links `url_id` if URL was updated.
  - `delete_monitor(monitor_id)`: Safely deletes monitor and all associated records.
- **`pagewatch/web/routes.py`** — Web routes & template filters:
  - Route `GET /`: Lists all monitors in a responsive table.
  - Route `GET/POST /monitors/add`: Validates name, URL, interval, sensitivity, and creates monitor.
  - Route `GET /monitors/<id>`: Detailed view of monitor configuration, selectors, and alert channels.
  - Route `GET/POST /monitors/<id>/edit`: Pre-populates and updates existing monitor.
  - Route `GET/POST /monitors/<id>/delete`: No-JavaScript confirmation page and deletion handler.
  - Template filters: `time_ago` (formats relative timestamps like "5 min ago", "just now", "never") and `format_interval` ("15 min", "1 hour", etc.).
- **Jinja2 Templates (Pico.css, server-rendered, 0 JavaScript)**:
  - `pagewatch/web/templates/base.html`: Updated with status dot indicators (green OK, red error, orange blocked, grey pending), noisy warning badges, and consistent nav links.
  - `pagewatch/web/templates/dashboard.html`: Full table view of monitors with action buttons (View, Edit, Delete).
  - `pagewatch/web/templates/add_monitor.html`: Clean form with server-side validation error boxes and collapsible advanced sections.
  - `pagewatch/web/templates/edit_monitor.html`: Pre-populated edit form.
  - `pagewatch/web/templates/delete_confirm.html`: Pure HTML confirmation dialog before deleting.
  - `pagewatch/web/templates/monitor.html`: Detailed monitor summary view.
- **Unit and Integration Tests**:
  - `tests/test_urlutils.py`: 15 tests for URL normalization and domain extraction.
  - `tests/test_monitors_web.py`: 8 integration tests covering database URL deduplication, repository operations, form validation, and web routes.

### Files created / modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/urlutils.py` | Created | URL validation and normalization |
| `pagewatch/monitors_repo.py` | Created | Database repository for monitors & URLs |
| `pagewatch/web/templates/add_monitor.html` | Created | Add monitor form template |
| `pagewatch/web/templates/edit_monitor.html` | Created | Edit monitor form template |
| `pagewatch/web/templates/delete_confirm.html` | Created | Delete confirmation template |
| `pagewatch/web/templates/monitor.html` | Created | Individual monitor detail template |
| `tests/test_urlutils.py` | Created | Unit tests for URL utilities |
| `tests/test_monitors_web.py` | Created | Unit & route integration tests |
| `pagewatch/web/routes.py` | Modified | Added full CRUD routes & template filters |
| `pagewatch/web/templates/base.html` | Modified | Added status dot styles & navigation |
| `pagewatch/web/templates/dashboard.html` | Modified | Added monitors table and action buttons |
| `pagewatch/config.py` | Modified | Added `ALLOW_LOCALHOST` setting |
| `.env.example` | Modified | Added `ALLOW_LOCALHOST=true` |

### Tested

- Ran `pytest -v`: **52 passed in 0.60s** (all 52 tests across `test_normalizer.py`, `test_urlutils.py`, `test_monitors_web.py`).
- Ran live Flask test:
  - Verified `GET /`
  - Verified `POST /monitors/add`
  - Verified monitor appears in dashboard table with pending status dot and formatted timestamps.

### Known issues

- None.

### What's next

- ~~Step 5~~ ✅
- Step 6 and beyond per PLAN.md

---

## Step 5: End-to-End Check Pipeline, Job Queue & Single Worker Thread ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

- **`pagewatch/jobqueue.py`** — SQLite-backed asynchronous queue:
  - `enqueue_job(url_id)`: Enqueues a job for `url_id` only if not already queued or running (deduplication per PLAN.md 5.3).
  - `claim_next_job()`: Atomically claims the oldest due job in an immediate transaction, sets `status='running'`, timestamps `started_at`, and increments `attempts`.
  - `finish_job(job_id)`: Marks job `status='done'` and records `finished_at`.
  - `fail_job(job_id, error)`: Implements exponential retry backoff (1 min, 2 min, 4 min) up to `MAX_RETRIES` (3); marks job as `failed` once retries are exhausted.
  - `reset_stuck_jobs(stuck_minutes=5)`: Recovers any jobs stuck in `running` state for more than 5 minutes.
- **`pagewatch/checker.py`** — Snapshot and comparison pipeline (PLAN.md 5.4 & 5.5):
  - `check_monitor(monitor, fetch_result)`:
    - If fetch failed: records `error` outcome, updates status and `check_log`.
    - If `include_selectors` match nothing: records error with `"Selector matched nothing"`.
    - Baseline check: saves text to `data/texts/<monitor_id>_<snapshot_id>.txt` and screenshot to `data/screenshots/<monitor_id>_<snapshot_id>.png`, inserts `snapshots` record, updates monitor timestamps.
    - Subsequent checks: if normalized hash matches, logs `unchanged` and avoids file writes.
    - If hash changed: compares text using `compare_texts` with monitor's sensitivity (`high`, `medium`, `low`); changes below threshold are logged as `unchanged` ("below sensitivity"). Meaningful changes create a new snapshot and track `noisy_streak`.
- **`pagewatch/worker.py`** — Single dedicated background thread:
  - `Worker` class: Launches one daemon thread that initializes and retains a single `BrowserSession` (Playwright headless Chromium).
  - Main loop: Atomically claims jobs from queue.
  - Fan-out (PLAN.md 5.2): Renders page once per URL, then runs `check_monitor` for every active monitor pointing to that URL. Updates `urls.last_fetched_at` and `last_http_status`.
  - Thread safety: Wrapped in robust try/except so worker thread never crashes.
- **`pagewatch/__init__.py`** — Lifecycle hooks:
  - Automatically runs `reset_stuck_jobs()`.
  - Initializes and starts the background `Worker` thread once.
- **Web Routes & UI Updates**:
  - `POST /monitors/<id>/check-now`: Enqueues a job and redirects with flash message `"Check queued"`.
  - Added "Check Now" button to both dashboard and monitor detail view.
  - Updated `/monitors/<id>` (and `/monitor/<id>`): displays monitor details, saved snapshots table with direct links to view stored text and screenshots, and the last 20 `check_log` entries.
  - Safe file serving endpoints: `/snapshots/<id>/text`, `/snapshots/<id>/screenshot`, `/files/texts/<filename>`, `/files/screenshots/<filename>`.
- **Unit and Integration Tests**:
  - `tests/test_checker.py`: 6 tests using mock fetch results (baseline creation, hash deduplication, sensitivity filtering, selector miss error, fetch failure).
  - `tests/test_jobqueue.py`: 4 tests verifying enqueue deduplication, atomic claiming, retries/backoff, and stuck job recovery.

### Files created / modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/jobqueue.py` | Created | SQLite job queue with atomic claim, backoff retries |
| `pagewatch/checker.py` | Created | Change detection pipeline, sensitivity logic & snapshots |
| `pagewatch/worker.py` | Created | Single worker thread owning Playwright and URL fan-out |
| `tests/test_checker.py` | Created | Unit tests for checker pipeline |
| `tests/test_jobqueue.py` | Created | Unit tests for job queue operations |
| `pagewatch/__init__.py` | Modified | Starts Worker thread & recovers stuck jobs on boot |
| `pagewatch/web/routes.py` | Modified | Added check-now endpoint, snapshot & log views, safe file serving |
| `pagewatch/web/templates/base.html` | Modified | Added flash messages banner container |
| `pagewatch/web/templates/dashboard.html` | Modified | Added Check Now button to actions column |
| `pagewatch/web/templates/monitor.html` | Modified | Added Check Now button, snapshots table, check log table |

### Tested

- Ran `pytest -v`: **62 passed in 1.20s** (all 62 tests across test suite).
- Ran live end-to-end check test against `testsite/app.py`:
  - Verified initial "Check Now" created baseline snapshot #1 and text/screenshot files on disk.
  - Verified second "Check Now" logged "Content unchanged" and did not duplicate snapshots.
  - Updated price on test site to $777, triggered "Check Now": verified meaningful change was detected, snapshot #2 was created.
  - Verified snapshot #2 text file served over HTTP contained `Price: $777`.

### Known issues

- None.

### What's next

- ~~Step 6~~ ✅
- Step 7 and beyond per PLAN.md

---

## Step 6: Failure Classification & Rate Limiting ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

- **`pagewatch/failures.py`** — Outcome classification (PLAN.md 5.6):
  - Pure function `classify_fetch(fetch_result)` mapping any fetch result into `ok`, `error`, or `blocked`.
  - Blocks on HTTP 403, 429, 503.
  - Blocks on Cloudflare / CAPTCHA text markers (`BLOCKED_MARKERS`: "captcha", "verify you are human", "access denied", "unusual traffic", "just a moment", "enable javascript and cookies").
  - Errors on HTTP >= 400 (e.g. 404, 500, 502), timeouts, DNS, and connection errors.
  - Errors on empty or near-empty pages (< 20 visible characters).
- **`pagewatch/ratelimit.py`** — Polite crawler behavior (PLAN.md 5.7):
  - `wait_for_domain(domain)`: Tracks last fetch times per domain, enforces at least `DOMAIN_DELAY_SECONDS` between requests. Sleeps in small 0.2s slices for responsive shutdown.
  - `is_allowed_by_robots(url)`: Uses `urllib.robotparser`, caches robots.txt per domain for 24h, allows access if missing or unreachable. Skips localhost when `config.ROBOTS_SKIP_LOCALHOST=True`.
  - `apply_backoff(url_id, retry_after_header)`: Parses Retry-After header or applies exponential doubling backoff up to 24h on HTTP 429/503.
- **Database & Schema Migration**:
  - Added `blocked_until TEXT` column to `urls` table in `pagewatch/db.py` with an automatic, safe `ALTER TABLE` migration for existing databases.
- **`pagewatch/checker.py`**:
  - Added random jitter (0 to 60 seconds) when calculating `next_check_at`.
- **`pagewatch/worker.py` Integration**:
  - Pre-fetch: Checks robots.txt (marks monitors `blocked` with `"robots.txt disallows this URL"` and skips fetch if disallowed).
  - Pre-fetch: Checks `blocked_until` backoff; respects domain rate limit via `wait_for_domain`.
  - Post-fetch: Runs `classify_fetch`. If outcome is `error` or `blocked`, skips content comparison and snapshot saving entirely; records check log and updates monitor status, status_message, and increments consecutive failures.
  - Left comment for Step 8: trigger site-down / blocked alert after 3 consecutive failures.
- **Dashboard UI Update**:
  - Updated `pagewatch/web/templates/dashboard.html` to display `status_message` in small text directly under the status dot.
- **Unit Tests**:
  - `tests/test_failures.py`: 12 tests covering 200 OK, 500, 404, 403, 429, 503, CAPTCHA markers, Cloudflare "just a moment", all blocked markers, < 20 character empty page, timeout, DNS error.
  - `tests/test_ratelimit.py`: 7 tests covering domain delay with time mocking, robots allow/disallow parsing, specific bot rules, localhost skip, and backoff calculations.

### Files created / modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/failures.py` | Created | Classification into ok, error, blocked outcomes |
| `pagewatch/ratelimit.py` | Created | Domain rate limiter, robots.txt parser, and backoff handler |
| `tests/test_failures.py` | Created | 12 tests for all failure and blocked conditions |
| `tests/test_ratelimit.py` | Created | 7 tests for rate limits, robots.txt, and backoff |
| `pagewatch/db.py` | Modified | Added `blocked_until` column and safe ALTER TABLE migration |
| `pagewatch/config.py` | Modified | Added `ROBOTS_SKIP_LOCALHOST` setting |
| `.env.example` | Modified | Added `ROBOTS_SKIP_LOCALHOST=true` |
| `pagewatch/checker.py` | Modified | Added random jitter (0-60s) to `next_check_at` |
| `pagewatch/worker.py` | Modified | Integrated robots checks, rate limiting, and failure handling |
| `pagewatch/web/templates/dashboard.html` | Modified | Added status message display under status dot |

### Tested

- Ran `pytest -v`: **83 passed in 1.34s** across entire test suite.
- Ran live test against `testsite/app.py`:
  - Verified `/captcha` page classified as `blocked`, `Blocked marker detected: 'captcha'` displayed on dashboard, 0 snapshots created.
  - Verified `/down` page classified as `error`, `HTTP 500 server or client error` displayed on dashboard, 0 snapshots created.

### Known issues

- None.

### What's next

- ~~Step 7~~ ✅
- **Step 8:** Alerts & Notifications per PLAN.md.

---

## Step 7: Automatic Periodic Checks & Scheduler ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

- **`pagewatch/scheduler.py`** — Periodic job scheduling using APScheduler `BackgroundScheduler`:
  - `scheduler_tick()`: Runs every 30 seconds. Calls `reset_stuck_jobs()`, selects all active monitors where `next_check_at <= now`, groups them by `url_id`, and calls `enqueue_job(url_id)` once per URL (fan-out pattern).
  - Strictly adheres to Playwright threading rules (PLAN.md 5.1): never touches Playwright objects.
  - Provides `start_scheduler()`, `stop_scheduler()`, and `is_scheduler_running()`.
- **Database Schema & Safe Migration (`pagewatch/db.py`)**:
  - Added optional `monitor_id INTEGER REFERENCES monitors(id)` to `jobs` table schema.
  - Safe `ALTER TABLE jobs ADD COLUMN monitor_id INTEGER REFERENCES monitors(id)` executed inside `create_tables()` with OperationalError suppression for existing databases.
- **Job Queue Update (`pagewatch/jobqueue.py`)**:
  - Updated `enqueue_job(url_id, monitor_id=None)` to accept optional `monitor_id` while maintaining deduplication per URL.
- **Monitors Repository Update (`pagewatch/monitors_repo.py`)**:
  - Updated `update_monitor`: resets `next_check_at = now` when a monitor is saved so edited monitors are evaluated promptly.
- **Worker Selective Fan-Out (`pagewatch/worker.py`)**:
  - Updated `_process_job`: If `job["monitor_id"]` is set (e.g., from "Check now"), only evaluates that specific monitor.
  - If `job["monitor_id"]` is NULL (periodic checks), queries only monitors where `next_check_at <= now`.
  - Ensures the page is fetched once per URL, but only actually due monitors have their `check_log` and `next_check_at` updated.
- **Application Factory (`pagewatch/__init__.py`)**:
  - Starts `start_scheduler()` in `init()` after starting the worker.
  - Exposes scheduler instance on `app.scheduler`.
- **Web UI & Routes (`pagewatch/web/routes.py` & `pagewatch/web/templates/dashboard.html`)**:
  - `DEV_FAST_MODE`: When enabled in `.env`, interval dropdown offers 1 min and 2 min options for rapid testing, and config validates intervals down to 1 minute with 2s domain delays.
  - `check_now` route passes `monitor_id` into `enqueue_job`.
  - Dashboard route calculates queue counts (queued, running, failed in last 24h) and scheduler status.
  - Dashboard footer status panel renders: Scheduler running (green/red dot), Queued jobs, Running jobs, Failed jobs (last 24h).
- **Unit & Integration Tests (`tests/test_scheduler.py`)**:
  - 10 tests covering: 3 monitors on same URL -> 1 job; future monitor -> 0 jobs; stuck job recovery; inactive monitor ignored; multiple URLs enqueued; scheduler start/stop lifecycle; worker selective evaluation; explicit monitor override; DEV_FAST_MODE dropdown options; and dashboard footer status panel rendering.

### Files created / modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/scheduler.py` | Created | APScheduler BackgroundScheduler and `scheduler_tick` |
| `tests/test_scheduler.py` | Created | 10 unit tests for scheduler, worker filtering, and UI stats |
| `pagewatch/db.py` | Modified | Added `jobs.monitor_id` column and safe ALTER TABLE migration |
| `pagewatch/jobqueue.py` | Modified | Updated `enqueue_job(url_id, monitor_id=None)` |
| `pagewatch/monitors_repo.py` | Modified | Reset `next_check_at = now` in `update_monitor` |
| `pagewatch/worker.py` | Modified | Filter monitors by `next_check_at <= now` or `job.monitor_id` |
| `pagewatch/__init__.py` | Modified | Hooked `start_scheduler()` into `init()` |
| `pagewatch/web/routes.py` | Modified | Fast mode choices, check-now monitor targeting, queue stats |
| `pagewatch/web/templates/dashboard.html` | Modified | Added queue & scheduler footer status panel |

### Tested

- Ran `pytest -v`: **93 passed in 1.82s** across all test suites.
- Verified scheduler tick deduplication: 3 monitors on same URL produce 1 queued job.
- Verified worker selective evaluation: only monitors with `next_check_at <= now` are checked on periodic runs.

### Known issues

- None.

### What's next

- ~~Step 8 (Diffs & Comparison UI)~~ ✅
- **Step 9:** Alerts & Notifications per PLAN.md.

---

## Step 8: Diffs & Comparison UI ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

- **`pagewatch/differ.py`** — Text Differencing using Python's `difflib`:
  - `text_diff_lines(old_text, new_text)`: Returns list of `(kind, line_text)` with kind in `"same"`, `"added"`, `"removed"` using `difflib.SequenceMatcher`.
  - `count_diff_lines(old_text, new_text)`: Counts added and removed line counts.
  - `side_by_side_html(old_text, new_text)`: Generates side-by-side HTML comparison table with 3 lines of context using `difflib.HtmlDiff`.
- **`pagewatch/imgdiff.py`** — Visual Screenshot Diffing using Pillow:
  - `make_diff_image(old_png_path, new_png_path, out_path)`: Opens both screenshots, pads smaller image with white canvas, computes `ImageChops.difference`, thresholds anti-aliasing noise, divides image into 40x40 pixel tiles (marking tiles changed if > 2% pixels differ), merges neighbouring tiles into bounding rectangles, draws 3px red boxes on a copy of the new screenshot, saves PNG, and returns the percentage of changed pixels.
  - `get_or_create_diff_image(a_id, b_id, old_path, new_path)`: Caches diff images in `data/diffs/` named `diff_<a>_<b>.png` so they are never recomputed.
- **Web UI & Routes (`pagewatch/web/routes.py`)**:
  - `/monitor/<id>`: Upgraded into a Version Timeline displaying snapshots newest first with relative timestamp, hash prefix, `+x/-y lines vs previous`, and screenshot thumbnail (styled with CSS width only), each linking directly to `/monitor/<id>/compare?a=<prev>&b=<this>`.
  - `/monitor/<id>/compare?a=<a>&b=<b>`: Dropdown selector form to compare ANY two snapshots of a monitor (plain GET form, no JS). Renders 4 views:
    1. Highlighted visual diff screenshot with red rectangles and "x percent of the page changed".
    2. Old and new screenshots side-by-side.
    3. Unified colored text diff (green added lines, red removed lines).
    4. Side-by-side text diff table (`difflib.HtmlDiff`).
  - Validates that snapshots belong to the monitor, handles identical selections, and displays friendly messages if text/screenshot files are missing from disk.
  - Safe data serving route `/data/<path:filepath>`: Strictly checks `os.path.commonpath` to ensure requested file is inside `DATA_DIR`, blocking path traversal attacks (`..`).
- **Templates**:
  - `pagewatch/web/templates/monitor.html`: Vertical timeline layout with thumbnail images and comparison links.
  - `pagewatch/web/templates/compare.html`: Responsive comparison view with snapshot selector, summary badge pills, side-by-side screenshots, unified diff, and side-by-side diff table with custom CSS keeping colors readable in both light and dark mode.
- **Unit & Integration Tests**:
  - `tests/test_differ.py`: 11 tests covering additions/removals detection, identical text comparison, side-by-side HTML generation, legitimate file serving, path traversal protection (403/404), 404 for missing files, full compare route rendering, identical snapshot validation, cross-monitor snapshot rejection, and timeline comparison links.
  - `tests/test_imgdiff.py`: 4 tests covering 0.0% change on identical images, positive percentage and red bounding box on changed images, dimension mismatch white padding, and diff image caching in `config.DIFF_DIR`.

### Files created / modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/differ.py` | Created | Unified and side-by-side text diffing using difflib |
| `pagewatch/imgdiff.py` | Created | Tile-based screenshot diffing and red box highlighting |
| `pagewatch/web/templates/compare.html` | Created | Four-section snapshot comparison template with dark mode styling |
| `tests/test_differ.py` | Created | 11 tests for text diffing, path traversal, and compare route |
| `tests/test_imgdiff.py` | Created | 4 tests for image diffing, padding, and caching |
| `pagewatch/config.py` | Modified | Added `DIFF_DIR` and auto-created `data/diffs/` folder |
| `pagewatch/web/routes.py` | Modified | Added version timeline logic, compare route, and safe /data/ route |
| `pagewatch/web/templates/monitor.html` | Modified | Replaced table with vertical version timeline |

### Tested

- Ran `pytest -v`: **108 passed in 2.03s** across all test suites.
- Verified path traversal protection: `/data/../secret.txt` returns 403 Forbidden.
- Verified visual diff on Pillow: identical images return 0.0%; modified images return positive percentage with red bounding rectangles.

### Known issues

- None.

### What's next

- ~~Step 9 (Alerts & Notifications)~~ ✅
- **Step 10:** Production Polish, Logging & Final Docs per PLAN.md.

---

## Step 9: Alerts & Notifications ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

- **`pagewatch/summary.py`** — Rule-based one-line change summary generation:
  - `make_summary(old_text, new_text)`: Detects if two snapshots differ mostly by one number (e.g., `"Number changed from 499 to 459"`). Otherwise returns added/removed line counts with up to 2 short examples trimmed to <= 80 chars (e.g., `"3 lines added, 1 removed: + '...', - '...'"`).
- **`pagewatch/alerts.py`** — Multi-channel notification dispatchers and deduplication:
  - Low-level senders: `send_email` via SMTP + STARTTLS (returns False and logs if SMTP not configured), `send_telegram` via Telegram Bot API `sendMessage`, `send_discord` via incoming webhook URLs. Never raises exceptions (catches, logs, continues).
  - Database-backed atomic deduplication: `record_alert(monitor_id, snapshot_id, channel, dedupe_key, summary)` inserts into the `alerts` table with `dedupe_key = f"{monitor_id}:{snapshot_id}:{channel}"`. If duplicate, SQLite UNIQUE constraint is caught and sending is skipped silently.
  - `notify_change(monitor, old_snapshot, new_snapshot, summary)`:
    - Never alerts on the baseline (first) snapshot.
    - Never alerts if `is_noisy == 1` (endless change guard).
    - If `daily_digest == 1`, skips instant alert (handled by scheduled digest).
    - Keyword rule: If `keyword` is set, only alerts when the keyword's presence changed (appeared or disappeared, case-insensitive).
    - Builds message containing monitor name, URL, summary, timestamp, and comparison diff link (`BASE_URL + /monitors/<id>/compare?a=<old>&b=<new>`).
  - `notify_status(monitor, kind, message)`:
    - Sends `"down"` or `"blocked"` status alert after 3 consecutive failures.
    - Uses failure episode marker (`last_checked_at` of last successful check) so only one alert is sent per downtime episode without spamming.
    - Sends `"recovered"` status alert once when the monitor succeeds after an outage.
  - `send_test_alert(monitor)`: Sends a harmless test notification to all configured channels without deduplication so users can verify settings.
  - Documented setup instructions for Telegram bot tokens (`@BotFather`) and Discord webhooks in top-level comments and `.env.example`.
- **`pagewatch/digest.py`** — Daily digest compilation and dispatch:
  - `build_digest_for_monitor(monitor, since)`: Compiles 24-hour summary of snapshots and changes for a monitor.
  - `send_daily_digests()`: Queries active monitors with `daily_digest = 1`, sends digest summaries, and deduplicates per day (`dedupe_key = f"{monitor_id}:digest:{date}:{channel}"`).
  - Added daily cron job at 09:00 in `pagewatch/scheduler.py`.
- **Checker and Worker Integration**:
  - `pagewatch/checker.py`: Dispatches `notify_change` on meaningful change (Case 4c); sends `notify_status("down")` if consecutive failures reaches 3; sends `notify_status("recovered")` when check succeeds after failure streak >= 3; clears `is_noisy = 0` whenever page stabilizes.
  - `pagewatch/worker.py`: Dispatches `notify_status` on 3 consecutive failures when robots.txt blocks crawling or when page fetch encounters non-ok classification (Case 10).
- **Web UI & Routes (`pagewatch/web/routes.py`)**:
  - Added `POST /monitors/<id>/test-alert`: Dispatches test notification to configured channels and flashes results.
  - Added `POST /admin/send-digest-now`: Demo endpoint guarded by `DEV_FAST_MODE` to test daily digests immediately.
  - Added "Send Test Alert" button on monitor detail page (`pagewatch/web/templates/monitor.html`).
  - Added "Send Daily Digest Now (Demo)" button on dashboard footer when `DEV_FAST_MODE` is enabled (`pagewatch/web/templates/dashboard.html`).
- **Tests**:
  - `tests/test_summary.py`: 8 unit tests for single number changes, decimals, line counts, trimming, and edge cases.
  - `tests/test_alerts.py`: 23 tests covering email/Telegram/Discord senders, error handling, deduplication, baseline skips, noisy guards, keyword rules, status down/recovery alerts, test alerts, daily digest compilation, and web routes.

### Files created / modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/summary.py` | Created | Rule-based one-line change summary generation |
| `pagewatch/alerts.py` | Created | Multi-channel alert dispatchers, deduplication, and status notifications |
| `pagewatch/digest.py` | Created | Daily digest compilation and dispatch |
| `tests/test_summary.py` | Created | 8 tests for summary generation |
| `tests/test_alerts.py` | Created | 23 tests for alert dispatch, deduplication, and digests |
| `pagewatch/scheduler.py` | Modified | Added 09:00 daily digest cron job |
| `pagewatch/checker.py` | Modified | Wired `notify_change`, `notify_status`, and noisy reset |
| `pagewatch/worker.py` | Modified | Wired `notify_status` on 3 consecutive failures |
| `pagewatch/web/routes.py` | Modified | Added test-alert and send-digest-now routes |
| `pagewatch/web/templates/monitor.html` | Modified | Added "Send Test Alert" button |
| `pagewatch/web/templates/dashboard.html` | Modified | Added demo digest button when `DEV_FAST_MODE=true` |
| `.env.example` | Modified | Added Telegram & Discord webhook instructions |

### Tested

- Ran `pytest`: **139 passed in 3.37s** across all test suites.
- Verified deduplication: Duplicate alert key rejected at DB level.
- Verified keyword rule: Alert sent when keyword appeared or disappeared; suppressed when keyword state did not change.
- Verified status alerts: Alert sent after 3 consecutive failures, deduplicated across further failures, and recovery alert sent on restore.

### Known issues

- None.

### What's next

- ~~Step 10: Audit & Hardening~~ ✅

---

## Step 10: Audit & Hardening ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was audited and hardened

1. **8 Core Requirements & 4 Design Questions**:
   - Comprehensive verification against `PLAN.md`. All 8 core requirements and all 4 design questions are fully satisfied (100% DONE).
2. **7 Critical Edge Cases**:
   - **App restart while a job is running**: Handled. On app startup in `init()`, `reset_stuck_jobs(stuck_minutes=0)` immediately recovers any orphaned running jobs back to queued state. `scheduler_tick` additionally checks every 30s.
   - **Two monitors on same URL with different selectors**: Handled. Page renders once in Playwright, then fans out to all active monitors. Each monitor applies its own selectors independently.
   - **Deleting a monitor with snapshots**: Hardened. `delete_monitor` in `monitors_repo.py` now queries all snapshot text files and screenshot PNGs and deletes them from disk, removes associated cached diff images, and cleans up all related DB rows (`jobs`, `alerts`, `number_points`, `check_log`, `snapshots`, `monitors`).
   - **URL that redirects**: Handled. Playwright `page.goto` follows HTTP and client redirects automatically, records `final_url`, and captures content from final target.
   - **Very large page text**: Hardened. In `checker.py`, page text is capped at 1 MB (`MAX_TEXT_SIZE_BYTES = 1024 * 1024`). Pages exceeding 1 MB are truncated with `[Truncated: page text exceeded 1 MB limit]`.
   - **Two quick "Check now" clicks**: Hardened. `enqueue_job` uses an atomic `BEGIN IMMEDIATE` SQLite transaction to check and insert, preventing duplicate jobs.
   - **Worker thread crash**: Hardened. `Worker._run_loop` wraps browser management in an outer loop with clear logging (`[Worker Fatal] ...`) and automatically reinitializes a fresh browser session if an unexpected crash occurs.
3. **Secrets & Gitignore**:
   - Verified `.gitignore` ignores `.env` (untracked in git).
   - Verified no secrets (passwords, bot tokens, webhooks) are printed in application logs.

### Files modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/monitors_repo.py` | Hardened | Added disk file deletion (texts, screenshots, diffs) in `delete_monitor` |
| `pagewatch/checker.py` | Hardened | Enforced 1 MB maximum text size limit |
| `pagewatch/jobqueue.py` | Hardened | Enforced atomic `BEGIN IMMEDIATE` check-and-insert in `enqueue_job` |
| `pagewatch/worker.py` | Hardened | Added auto-restart loop and fatal crash logging |
| `pagewatch/__init__.py` | Hardened | Reset running jobs immediately on startup (`stuck_minutes=0`) |
| `tests/test_monitors_web.py` | Updated | Added test for file and DB cleanup on monitor delete |
| `tests/test_checker.py` | Updated | Added test for 1 MB page text truncation |

### Tested

- Ran `pytest`: **141 passed in 4.98s** across all 12 test suites.

### Remaining Gaps / Future Bonus Items (Optional per PLAN.md Section 1)

- ~~Number tracking with a chart (`matplotlib`)~~ ✅
- Per-page RSS feed
- Visual selector picker (optional JS helper)

---

## Bonus Feature: Number Tracking & Visual Charting ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

1. **`pagewatch/numbers.py`**:
   - `parse_number(text)`: Pure function that extracts and converts numeric strings into Python floats across international currencies and formats:
     - Indian grouping: `₹1,299.50`, `1,23,456`, `1,23,456.75`
     - Western currencies: `$ 499`, `$12.99/mo`, `10,000`
     - European comma decimals: `€ 99,99`, `1.234,50 €`
     - Negative numbers: `-42`, `- 15.5`
     - Ratings and counts: `4.5 stars`, `99.5%`, `Only 3 left in stock`
     - Zeroes and decimals: `0`, `0.05`, `+250.75`
     - Returns `None` for non-numeric text (`Free`, empty string, None).
   - `extract_number_from_html(html, number_selector)`: Parses HTML with BeautifulSoup/lxml, locates the element matching CSS `number_selector`, and parses the number.
   - `record_number_point(monitor_id, snapshot_id, value, taken_at)`: Stores data point in `number_points` SQLite table. Called on both changed checks (with `snapshot_id`) and unchanged checks (with `snapshot_id=None`), ensuring continuous regular points for charting.
   - `check_and_alert_thresholds(monitor, value, snapshot_id)`: Evaluates `number_alert_below` and `number_alert_above`. If crossed, dispatches alert via `alerts.py` using per-value deduplication keys (`f"{monitor_id}:thresh_{condition}:{value}:{channel}"`).
   - `generate_number_chart(monitor)`: Generates time-series line chart of the last 200 recorded points using Matplotlib with headless `Agg` backend. Renders formatted timestamps on x-axis, title, grid, and optional threshold lines (`Alert Below` in red, `Alert Above` in orange). If no points exist, displays an informative placeholder. Returns raw PNG bytes.

2. **Database Migrations (`pagewatch/db.py`)**:
   - Added `number_alert_below REAL` and `number_alert_above REAL` columns to `monitors` table.
   - Implemented safe `ALTER TABLE` migrations in `create_tables()` preserving existing databases.

3. **Repository & Checker Integration**:
   - `pagewatch/monitors_repo.py`: Storing and retrieving `number_alert_below` and `number_alert_above` in `create_monitor` and `update_monitor`.
   - `pagewatch/checker.py`: Added `_handle_number_tracking` invoked after every OK fetch across baseline checks, meaningful changes, and unchanged checks.

4. **Web UI & Routes (`pagewatch/web/routes.py`)**:
   - Added routes `/monitors/<id>/chart.png` and `/monitor/<id>/chart.png` returning Matplotlib PNG image with `mimetype="image/png"`.
   - Updated monitor creation and edit forms (`add_monitor.html`, `edit_monitor.html`) with threshold inputs.
   - Updated monitor detail page (`monitor.html`) to render the number tracking chart image and threshold indicators when `number_selector` is configured.

5. **Tests (`tests/test_numbers.py`)**:
   - 17 unit and integration tests covering:
     - `parse_number` with 15+ formats.
     - `extract_number_from_html` with valid and missing selectors.
     - `record_number_point` persistence in database.
     - Threshold alerting (`number_alert_below`, `number_alert_above`, and deduplication).
     - Chart generation for empty state and multi-point state with threshold lines.
     - HTTP chart route verification (`200 OK`, `image/png`).
     - Checker end-to-end integration verifying number points recorded on baseline and unchanged checks.

### Files created / modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/numbers.py` | Created | Number parsing, threshold alerts, and Matplotlib chart generator |
| `tests/test_numbers.py` | Created | 17 unit & integration tests for number tracking |
| `pagewatch/db.py` | Modified | Added threshold alert columns with safe migrations |
| `pagewatch/monitors_repo.py` | Modified | Handled threshold fields in create/update |
| `pagewatch/checker.py` | Modified | Wired `_handle_number_tracking` for all OK checks |
| `pagewatch/web/routes.py` | Modified | Added `/monitor/<id>/chart.png` route & threshold validation |
| `pagewatch/web/templates/add_monitor.html` | Modified | Added threshold inputs |
| `pagewatch/web/templates/edit_monitor.html` | Modified | Added threshold inputs |
| `pagewatch/web/templates/monitor.html` | Modified | Embedded number tracking chart |

### Tested

- Ran `pytest`: **158 passed in 7.02s** across all 13 test suites.
- Verified chart generation with headless Agg backend (no GUI thread dependency).
- Verified point insertion on unchanged checks and deduplicated threshold alerting.

---

## Bonus Feature: Per-Page RSS 2.0 Feeds ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

1. **`pagewatch/feeds.py`**:
   - `generate_rss_feed(monitor) -> str`: Builds standard RSS 2.0 XML by hand using standard library `xml.etree.ElementTree` (zero external dependencies).
   - Channel elements:
     - `title`: Monitor name
     - `link`: Monitor page URL (`{config.BASE_URL}/monitors/{monitor_id}`)
     - `description`: Change feed description with target URL
     - `language`: `en`
     - `lastBuildDate`: Formatted RFC 822 date of latest snapshot
   - Snapshot items:
     - Up to 50 latest snapshots, ordered chronologically newest first.
     - `title`: Change summary (from `snapshots.summary` or fallback)
     - `link`: Direct URL to comparison with previous snapshot (`/monitors/<id>/compare?a=<old>&b=<new>`), or monitor page for baseline
     - `guid`: Snapshot ID with `isPermaLink="false"`
     - `pubDate`: RFC 822 date formatted with `format_rfc822(taken_at)`
     - `description`: Text change summary + direct compare link
   - Formatted with `xml.etree.ElementTree.indent(rss, space="  ")`.

2. **Database Migrations (`pagewatch/db.py`)**:
   - Added `summary TEXT NOT NULL DEFAULT ''` column to `snapshots` table.
   - Added safe `ALTER TABLE snapshots ADD COLUMN summary TEXT NOT NULL DEFAULT ''` migration preserving existing databases.

3. **Checker Pipeline Integration (`pagewatch/checker.py`)**:
   - In baseline snapshot creation (Case 3): stores `summary="Baseline snapshot created"`.
   - In meaningful change creation (Case 4c): calls `make_summary(old_text, cleaned_text)` and stores result in `snapshots.summary`.

4. **Web UI & Routes (`pagewatch/web/routes.py`, templates)**:
   - Added routes `/monitor/<id>/feed.xml` and `/monitors/<id>/feed.xml` serving RSS XML with `mimetype="application/rss+xml; charset=utf-8"`.
   - Added `{% block extra_head %}` in `pagewatch/web/templates/base.html`.
   - Added `<link rel="alternate" type="application/rss+xml" title="{{ monitor.name }} RSS Feed" href="/monitors/{{ monitor.id }}/feed.xml">` in `pagewatch/web/templates/monitor.html`.
   - Added visible "RSS Feed" button in the action bar and RSS link in monitor metadata.

5. **Tests (`tests/test_feeds.py`)**:
   - 7 unit and integration tests covering:
     - `format_rfc822` conversion and error handling.
     - `generate_rss_feed` XML structure and parsing with `xml.etree.ElementTree.fromstring`.
     - Snapshot items, links, GUIDs, summaries, and latest 50 item cap.
     - HTTP routes returning `200 OK` and `application/rss+xml`.
     - Checker populating `snapshots.summary` on baseline and change checks.
     - Template rendering of visible button and head alternate link.

### Files created / modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/feeds.py` | Created | Hand-built RSS 2.0 XML generator using ElementTree |
| `tests/test_feeds.py` | Created | 7 unit & integration tests for RSS feed generation |
| `pagewatch/db.py` | Modified | Added summary column to snapshots table with safe migration |
| `pagewatch/checker.py` | Modified | Saved change summary in snapshots table |
| `pagewatch/web/routes.py` | Modified | Added `/monitor/<id>/feed.xml` route |
| `pagewatch/web/templates/base.html` | Modified | Added extra_head block |
| `pagewatch/web/templates/monitor.html` | Modified | Added alternate head tag, RSS action button, and link |

### Tested

- Ran `pytest`: **165 passed in 8.17s** across all 14 test suites.
- Validated XML with standard RSS 2.0 readers and ElementTree parser.

---

## Summary Generation Improvements ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was improved

1. **`pagewatch/summary.py`**:
   - `make_summary(old_text, new_text, keyword=None) -> str`: Enhanced deterministic, rule-based change summarizer with prioritized heuristics:
     - **Price/Number changes with percentage**: Identifies single number modifications, calculates signed percentage change (`((new - old) / old) * 100`), checks context for currency symbols/indicators (`$`, `€`, `£`, `₹`, `price`, `cost`), and outputs:
       - Price drops: `"Price dropped from 499 to 459 (-8.0%)"`
       - Price rises: `"Price rose from 100 to 125 (+25.0%)"`
       - Non-price changes: `"Number dropped from 50 to 40 (-20.0%)"` or `"Number rose from 100 to 150 (+50.0%)"`
     - **Stock status phrase flips**: Detects inventory status transitions between "Out of stock" / "Sold out" and "In stock" / "Back in stock":
       - `"Changed from 'Out of stock' to 'In stock'"`
       - `"Changed from 'In stock' to 'Out of stock'"`
     - **Keyword appearance/disappearance**: Detects when a monitor's configured keyword appears or disappears:
       - `"Keyword '{keyword}' appeared"`
       - `"Keyword '{keyword}' disappeared"`
     - **New section appearing**: Detects added Markdown headings (`#`, `##`, `###`), colon headers (`Specifications:`, `Customer Reviews:`), or bracketed headers (`[Release Notes]`):
       - `"New section appeared: '{heading}'"`
     - **Deterministic fallback**: Retains line count difference with up to 2 trimmed examples:
       - `"{added_count} lines added, {removed_count} removed: + '...', - '...'"`

2. **Timeline & Alerts Display**:
   - **Timeline (`pagewatch/web/templates/monitor.html`)**: Displays the change summary prominently (`📝 {{ s.summary }}`) on each version snapshot card.
   - **Routes fallback (`pagewatch/web/routes.py`)**: Computes summary on-the-fly for historical snapshots captured prior to the column addition.
   - **Checker & Digest integration (`pagewatch/checker.py`, `pagewatch/digest.py`)**: Passes `keyword=monitor.get("keyword")` to `make_summary` so monitor-specific keyword events are highlighted.
   - **Alert notifications (`pagewatch/alerts.py`)**: Included in alert bodies and message payloads across Email, Telegram, and Discord.

3. **Tests (`tests/test_summary.py`)**:
   - 14 comprehensive unit tests verifying price drops/rises with percentages, stock phrase flips, keyword appearance/disappearance, new sections, line counting, trimming, and identical/empty texts.

### Files modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/summary.py` | Modified | Added percent calculation, stock flips, keyword detection, and section heuristics |
| `tests/test_summary.py` | Modified | 14 unit tests for all summary rules |
| `pagewatch/checker.py` | Modified | Passed monitor keyword to make_summary |
| `pagewatch/digest.py` | Modified | Passed monitor keyword to make_summary |
| `pagewatch/web/routes.py` | Modified | Handled historical snapshot summary fallback |
| `pagewatch/web/templates/monitor.html` | Modified | Rendered summary on snapshot timeline cards |

### Tested

- Ran `pytest`: **171 passed in 7.10s** across all 14 test suites.

---

## Step 12: Documentation & Latency Benchmarks (`README.md`) ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

1. **`scripts/measure.py`**:
   - Automated benchmarking tool running against local test site (`testsite/app.py`).
   - Ran 20 checks of an unchanged page (verifying dynamic timestamp, counter, and banner noise is filtered).
   - Ran 5 checks with price changes.
   - Evaluated 5 monitors on the same URL to verify 1-fetch fan-out.
   - Measured real performance: Average check duration: 637.5 ms, Median: 634.6 ms, Min: 621.7 ms, Max: 665.8 ms.
   - Confirmed snapshot creation behavior: Exactly 6 snapshots created (1 baseline + 5 changed; 0 for the 20 unchanged checks).
   - Confirmed 1 single network fetch served all 5 monitors.

2. **`README.md`**:
   - Section 1: Overview, key features, and screenshots placeholder list.
   - Section 2: Step-by-step setup and run instructions with Windows PowerShell commands.
   - Section 3: Full ASCII architecture diagram and module guide.
   - Section 4: Short, concrete answers in plain English for all 4 design questions, each ending with "Implemented in: <file/function>".
   - Section 5: Real measured latency and benchmark results from `scripts/measure.py`, timeouts, and retry behavior.
   - Section 6: Comprehensive failure handling table (outages, CAPTCHAs, timeouts, robots.txt, noisy pages, missing selectors).
   - Section 7: 5-minute live demo script (numbered step-by-step walkthrough).
   - Section 8: Honest known limitations (single worker thread, SQLite, no user auth, browser overhead).
   - Section 9: Instructions to run all 171 automated tests via pytest.

### Files created / modified

| File | Status | Purpose |
|---|---|---|
| `scripts/measure.py` | Created | Benchmark and latency measurement script |
| `README.md` | Created | Project documentation and final deliverable |
| `PROGRESS.md` | Modified | Updated progress tracking |

### Tested

- Ran `scripts/measure.py`: Successfully recorded 25 checks and fan-out verification.
- Ran `pytest`: **171 passed in 7.10s** across all 14 test suites.

---

## Step 13: Visual Region Picker (Bonus Feature) ✅

**Status:** DONE  
**Date:** 2026-10-16

### What was built

1. **`pagewatch/picker.py`**:
   - `generate_css_selector(soup, element)`: Generates clean, unique CSS selectors adhering to preference hierarchy:
     1. Unique element ID (`#product-price`).
     2. Unique `data-*` attribute (`span[data-testid="stock-badge"]`).
     3. Unique tag + class path (`div.price-card`).
     4. Hierarchical path using `:nth-of-type(n)` fallback (`main > article > p:nth-of-type(2)`).
   - `capture_picker_snapshot(browser_session, url, monitor_id, out_png_path, out_json_path)`: Uses the single background Playwright browser instance inside the worker thread to capture a full-page PNG screenshot and evaluate up to 300 visible DOM elements with their exact pixel bounding boxes (`x, y, w, h`) and unique CSS selectors.
   - `add_selector_to_monitor(monitor_id, selector_type, selector)` & `remove_selector_from_monitor(...)`: Manages newline-delimited `include_selectors` and `ignore_selectors` in SQLite.

2. **Job Queue & Worker Integration**:
   - Added `job_type TEXT NOT NULL DEFAULT 'check'` to `jobs` table with safe migration in `pagewatch/db.py`.
   - Updated `enqueue_job(url_id, monitor_id=None, job_type="check")` with deduplication per monitor for `picker_snapshot` jobs.
   - Background `Worker._process_job` branches on `job_type`: when `'picker_snapshot'`, calls `capture_picker_snapshot` without altering monitor check cycles or logs.

3. **Web Routes & UI Templates**:
   - `GET /monitor/<id>/picker` & `/monitors/<id>/picker`: If assets exist, renders `picker.html`; otherwise queues a worker job and renders `picker_loading.html` with `<meta http-equiv="refresh" content="3">` ("Preparing page... refresh in a few seconds").
   - `POST /monitors/<id>/picker/add` & `remove`: Appends or removes selectors without complex client-side state.
   - `POST /monitors/<id>/picker/refresh`: Invalidates cached files and re-triggers snapshot capture.
   - `pagewatch/web/templates/picker.html`: Displays full screenshot inside an `overflow-x: auto` container with absolutely positioned, semi-transparent `.picker-box` overlays.
   - Sticky selection toolbar showing current selector and "Watch this region" / "Ignore this region" buttons.
   - Region selector management cards with individual Remove buttons.
   - Kept standard textareas for selectors on Add/Edit monitor forms fully operational.
   - Direct button in monitor header and link under "Region Selectors" section on `monitor.html`.
   - **JavaScript Constraint**: Exactly 43 lines of vanilla JavaScript, heavily commented on every line in plain English, with zero external libraries/frameworks.

4. **Testing (`tests/test_picker.py`)**:
   - 11 comprehensive unit and integration tests:
     - Selector generation for elements with ID.
     - Selector generation for elements without ID (data attributes, classes, nested nth-of-type).
     - Selector additions, deduplication, and removals in the database.
     - Web route loading state with meta refresh tag.
     - Web route canvas display with overlay boxes.
     - Web route add, remove, and refresh endpoints.
     - End-to-end Playwright page capture with real bounding box measurements and selector resolution.

### Files created / modified

| File | Status | Purpose |
|---|---|---|
| `pagewatch/picker.py` | Created | CSS selector generation, Playwright snapshot extraction, and selector management |
| `pagewatch/web/templates/picker.html` | Created | Interactive visual picker template with screenshot canvas, overlay boxes, and <50 lines commented JS |
| `pagewatch/web/templates/picker_loading.html` | Created | Loading page with `<meta http-equiv="refresh" content="3">` |
| `tests/test_picker.py` | Created | 11 unit and integration tests for picker logic and routes |
| `pagewatch/config.py` | Modified | Added `PICKER_DIR` path and directory creation |
| `pagewatch/db.py` | Modified | Added `job_type` column to `jobs` table with safe migration |
| `pagewatch/jobqueue.py` | Modified | Supported `job_type` in `enqueue_job` with deduplication |
| `pagewatch/worker.py` | Modified | Added `_process_picker_job` handler in background worker |
| `pagewatch/web/routes.py` | Modified | Added picker GET and POST routes |
| `pagewatch/web/templates/monitor.html` | Modified | Added Visual Picker button and link under Region Selectors |
| `pagewatch/monitors_repo.py` | Modified | Cleaned up cached picker files on monitor deletion |
| `PROGRESS.md` | Modified | Updated progress documentation |

### Tested

- Ran `pytest`: **182 passed in 9.37s** across all 15 test suites.


