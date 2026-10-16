# PageWatch: Antigravity Prompts (step by step)

## How to use this file

1. Put `PLAN.md` in your project root folder (`pagewatch/`). Open that folder as the workspace in Antigravity.
2. Do the steps IN ORDER. Do not skip ahead and do not paste two steps together.
3. For every step, follow this loop:
   - Paste the prompt in the Antigravity agent chat.
   - Read its plan first. If it says something you do not understand, ask: "Explain this in simple Hinglish."
   - Let it write code, then run the **Verify** commands yourself.
   - If verify passes: `git add .` then `git commit -m "step N done"`.
   - If verify fails: use the **Fix prompt** at the bottom of this file.
4. If a step takes more than ~2 hours with no progress, stop and ask me (or use the "stuck" prompt below).

Time guide (rough, for a beginner with an agent): Steps 1 to 5 are the foundation. Steps 6 to 10 finish the core spec. Steps 11 to 13 are polish and bonus. If time is short, finish through Step 10 and Step 12 (README) and submit. That is a complete project.

---

## STEP 0: Manual setup (you do this, no agent)

Open PowerShell in the folder where you want the project.

```
mkdir pagewatch
cd pagewatch
python --version
python -m venv venv
venv\Scripts\activate
pip install flask playwright pillow requests python-dotenv apscheduler matplotlib pytest
playwright install chromium
pip freeze > requirements.txt
git init
```

Copy `PLAN.md` into this folder. Create a file `.gitignore` with:

```
venv/
data/
.env
__pycache__/
*.pyc
```

Python version should be 3.11 or newer. If `python --version` shows older, install the latest from python.org first.

Verify: `python -c "import flask, playwright, PIL; print('ok')"` prints `ok`.

Commit: `git add . && git commit -m "step 0 setup"`

---

## STEP 1: Skeleton, config and database

**Paste this:**

```
Read PLAN.md fully before doing anything. I am a beginner, follow section 0 strictly.

TASK (Step 1 only): create the project skeleton, config and database layer.

1. Create the folder structure from PLAN.md section 3. Create all folders. For module files that belong to later steps, do NOT create them yet, except these for now: run.py, pagewatch/__init__.py, pagewatch/config.py, pagewatch/db.py, pagewatch/web/routes.py, pagewatch/web/templates/base.html, pagewatch/web/templates/dashboard.html.
2. config.py: load .env using python-dotenv. Define constants with defaults: DATA_DIR ("data"), DB_PATH, SCREENSHOT_DIR, TEXT_DIR, MIN_INTERVAL_MINUTES (15), MAX_INTERVAL_MINUTES (1440), PAGE_TIMEOUT_SECONDS (45), MAX_RETRIES (3), DOMAIN_DELAY_SECONDS (10), BASE_URL ("http://127.0.0.1:5000"), SMTP settings, TELEGRAM_BOT_TOKEN. Create the data folders automatically if missing.
3. db.py: write get_connection() (sqlite3 with row_factory so rows behave like dicts, WAL mode on, foreign keys on), and create_tables() that creates ALL tables exactly as in PLAN.md section 4. Also write two tiny helpers: run_query(sql, params) for SELECT returning list of rows, and run_write(sql, params) for INSERT/UPDATE returning lastrowid.
4. pagewatch/__init__.py: write init() which (a) calls create_tables(), (b) creates the Flask app, (c) registers the routes blueprint, (d) returns the app. Later steps will add more hooks inside init(), so write clear comment placeholders like "# STEP 7 will start the scheduler here" (comments only, no code).
5. routes.py: one route "/" that renders dashboard.html showing "PageWatch is running" and a count of monitors from the DB (will be 0).
6. base.html: Pico.css from CDN, a simple nav bar with "Dashboard" and "Add monitor" links (the add page does not exist yet, link can be dead for now).
7. run.py: imports init(), runs app on port 5000 with debug off (debug reloader creates two processes which will break our worker thread later).
8. .env.example with all config keys, no real secrets.

Do NOT write fetcher, checker, scheduler or any feature code.
When done: tell me the exact commands to run and what I should see. Update PROGRESS.md (create it).
```

**Verify:**
```
python run.py
```
Open http://127.0.0.1:5000 and see "PageWatch is running". Check that `data/pagewatch.db` exists. Stop with Ctrl+C.

---

## STEP 2: The fetcher (Playwright) as a standalone script

**Paste this:**

```
Read PLAN.md fully. Follow section 0 (beginner, simple Python, comments).

TASK (Step 2 only): build pagewatch/fetcher.py, and a small test script scripts/try_fetch.py. No database use in this step.

fetcher.py requirements:
1. A class BrowserSession with methods start(), stop(), fetch_page(url, timeout_seconds, ignore_selectors=None). It uses Playwright sync API with Chromium headless. start() launches the browser once (reused for many fetches), stop() closes it.
2. fetch_page opens a NEW browser context per fetch (clean cookies, no stored credentials), with User-Agent "PageWatchBot/1.0 (+student project)", viewport 1280x800.
3. It navigates with wait_until="load" then additionally waits for network idle with a short cap (max 5 seconds, do not fail if it never goes idle).
4. It returns a plain dict (not a custom class) with keys: ok (bool), http_status (int or None), final_url, html, page_text (visible text via document.body.innerText), screenshot_bytes (full page PNG), error_type (None, "timeout", "dns", "connection", "other"), error_message, duration_ms.
5. Catch Playwright errors and convert them into the dict (ok=False plus error_type), never let an exception escape from fetch_page.
6. Important: leave a clear comment at the top of the file: "All Playwright objects must only be used in ONE thread. See PLAN.md section 5.1."
7. Do not apply noise filtering or selectors here. That is a later step. Just add a parameter placeholder if needed but keep it unused.

scripts/try_fetch.py: takes a URL from the command line, calls BrowserSession, prints http_status, duration, first 300 characters of page_text, and saves the screenshot as data/try_fetch.png.

Also create testsite/app.py exactly as described in PLAN.md section 6 (Flask on port 5001) so I can test against my own site. Keep it simple.

Do NOT touch the database or Flask main app.
When done tell me the commands to run. Update PROGRESS.md.
```

**Verify (two PowerShell windows):**
```
# window 1
python testsite/app.py

# window 2
python scripts/try_fetch.py http://127.0.0.1:5001/
python scripts/try_fetch.py http://127.0.0.1:5001/down
python scripts/try_fetch.py https://example.com
```
Expected: first prints status 200 and page text with price. `/down` prints status 500. Screenshot `data/try_fetch.png` opens and looks right. Visit `http://127.0.0.1:5001/` in your browser and refresh a few times to see timestamp, banner and counter change.

---

## STEP 3: Normalizer (noise filtering) with tests

**Paste this:**

```
Read PLAN.md fully. Follow section 0.

TASK (Step 3 only): build pagewatch/normalizer.py and tests/test_normalizer.py. Pure functions, no database, no Playwright.

normalizer.py functions:
1. normalize_text(raw_text) -> str: implement PLAN.md section 5.5 points 3 and 4 (regex replacement of timestamps, dates, "x minutes ago", counters like "1,234 views", UUIDs, long random hex/base64 tokens, then whitespace cleanup, drop empty lines). Put every regex in a clearly named module-level constant with a comment and an example string it matches.
2. hash_text(text) -> str: SHA-256 hex.
3. compare_texts(old_text, new_text, sensitivity) -> dict with keys: is_meaningful (bool), changed_line_percent (float), added_lines (list), removed_lines (list). Implement the sensitivity thresholds from PLAN.md 5.5 point 5 using difflib. Put the thresholds in config.py as constants.
4. extract_text_from_html(html, include_selectors, ignore_selectors) -> str: this one needs an HTML parser. Use ONLY the Python standard library plus BeautifulSoup4 (pip install beautifulsoup4 lxml). First remove script/style/noscript/iframe/svg, then the built-in ad selectors (define a list constant AD_SELECTORS in normalizer.py), then the monitor's ignore selectors. If include_selectors is not empty, keep only the text inside elements matching those selectors (join them in document order); if none match, return an empty string and make the caller able to detect that. Selectors are given as a multi-line string, one per line, so write a helper parse_selector_lines(text).
   Wrap invalid selector handling in try/except and skip bad selectors (do not crash), but return a list of bad selectors so the UI can warn later.

Tests in tests/test_normalizer.py (pytest), at least 12 tests, covering: timestamps removed, counters removed, UUID removed, two texts differing only by timestamp give the same hash, a real price change gives a different hash, each sensitivity level behaves as per the plan with a concrete example, ignore selector removes a region, include selector keeps only a region, bad selector does not crash.

Add beautifulsoup4 and lxml to requirements.txt. Do not touch other files.
When done tell me how to run pytest and what output to expect. Update PROGRESS.md.
```

**Verify:**
```
pip install beautifulsoup4 lxml
pip freeze > requirements.txt
pytest -q
```
Expected: all tests pass. Ask the agent: "Explain compare_texts in simple words with an example" so you understand it.

---

## STEP 4: Add monitor form and dashboard

**Paste this:**

```
Read PLAN.md fully. Follow section 0. No JavaScript.

TASK (Step 4 only): users can add, list, edit and delete monitors via the web UI. No fetching yet.

1. URL normalization helper in a new file pagewatch/urlutils.py: normalize_url(url) (lowercase scheme and host, strip fragment, strip trailing slash, require http or https, reject anything else, reject localhost only if config ALLOW_LOCALHOST is False; default ALLOW_LOCALHOST=True because I test on my own machine) and get_domain(url). Add tests in tests/test_urlutils.py.
2. Routes in routes.py (keep routes thin, put DB logic in a new file pagewatch/monitors_repo.py with functions create_monitor, list_monitors, get_monitor, update_monitor, delete_monitor):
   - GET/POST /monitors/add: form with name, url, interval (dropdown: 15 min, 30 min, 1 h, 3 h, 6 h, 12 h, 24 h), sensitivity (low/medium/high, default medium), include selectors (textarea, one per line), ignore selectors (textarea), keyword (optional), number selector (optional), alert email, Telegram chat id, Discord webhook URL, daily digest checkbox.
   - Validate on the server: name required, URL valid, interval between MIN and MAX minutes from config. Show friendly error messages on the form.
   - GET /monitors/<id>/edit and POST to update; POST /monitors/<id>/delete (with a confirm page, no JS).
   - On create: insert into urls if the normalized URL does not exist yet (one row per URL, see PLAN.md 5.2), then insert the monitor with status "pending" and next_check_at = now.
3. Dashboard (/) lists all monitors in a table: name, URL, interval, status (with a coloured dot: green OK, red error, orange blocked, grey pending), last checked, last changed, a warning badge if is_noisy, buttons Edit and View. Show "never" when empty. Format times in a readable way (e.g. "5 min ago").
4. Keep all pages server-rendered Jinja templates extending base.html, Pico.css only.

Do NOT implement the check logic, scheduler or Check now button yet.
When done tell me what to click to test and what I should see. Update PROGRESS.md.
```

**Verify:** `python run.py`, add 2 monitors (one with `http://127.0.0.1:5001/`, one with `https://example.com`), try an invalid URL and interval 5 (should be rejected), add a second monitor with the same URL and check in `data/pagewatch.db` that `urls` has only one row for it (use "DB Browser for SQLite" or ask the agent for a script `scripts/show_db.py` that prints table counts). Run `pytest -q`.

---

## STEP 5: The checker pipeline + worker thread + "Check now"

**Paste this:**

```
Read PLAN.md fully, especially sections 5.1, 5.2, 5.3 and 5.4. Follow section 0.

TASK (Step 5 only): make one check work end to end through a job queue and a single worker thread. No periodic scheduler yet. No failure classification yet (just treat ok=False as outcome "error"). No alerts yet. No diff UI yet.

1. pagewatch/jobqueue.py (uses the jobs table):
   - enqueue_job(url_id): inserts a queued job unless a queued/running job for that url_id already exists (return None in that case).
   - claim_next_job(): atomically takes the oldest queued job whose run_after is in the past, marks it running, sets started_at, increments attempts; returns the job or None. Use a single SQL transaction so two callers can never take the same job.
   - finish_job(job_id) and fail_job(job_id, error): fail_job implements retries with backoff 1, 2, 4 minutes up to MAX_RETRIES (put job back to queued with run_after in the future), after that status failed.
   - reset_stuck_jobs(): any job running for more than 5 minutes goes back to queued.
2. pagewatch/checker.py:
   - check_monitor(monitor_row, fetch_result): implements PLAN.md 5.4 for one monitor using extract_text_from_html + normalize_text + hash_text from normalizer.py. First check = baseline snapshot, no change flag. Saves text to data/texts/<monitor_id>_<snapshot_id>.txt and screenshot to data/screenshots/<monitor_id>_<snapshot_id>.png. If hash unchanged: only update last_checked_at and write check_log. Use compare_texts with the monitor's sensitivity as described in PLAN.md 5.5 (below threshold = unchanged, no snapshot). Updates monitor status to "ok", sets last_checked_at, last_changed_at, next_check_at = now + interval. Returns a small dict: outcome, snapshot_id (or None), message.
   - If include_selectors are set but match nothing, treat as error with message "Selector matched nothing".
3. pagewatch/worker.py:
   - A class Worker with start() that launches ONE background thread. That thread creates BrowserSession (from fetcher.py) once, then loops: claim_next_job(); if none, sleep 2 seconds; if a job exists: load the URL, fetch it ONCE, then for every active monitor attached to that url_id call check_monitor with the same fetch result (fan-out, PLAN.md 5.2). Wrap everything per job in try/except so the thread never dies; on exception call fail_job.
   - stop() cleanly stops the thread and closes the browser.
   - Update urls.last_fetched_at and last_http_status after each fetch.
4. In init(): call reset_stuck_jobs() and start the Worker (comment: "STEP 7 adds the scheduler next to this"). Make sure the worker starts only once (no debug reloader).
5. Routes: POST /monitors/<id>/check-now (button on dashboard and on a new monitor detail page /monitor/<id>) that only calls enqueue_job and redirects with a flash message "Check queued". The detail page /monitor/<id> shows monitor info, the last 20 check_log rows, and the list of snapshots (timestamp, hash first 8 chars, link to view stored text and screenshot via a safe route that serves files from data/).
6. Tests in tests/test_checker.py using a fake fetch_result dict (no real browser): baseline created, unchanged hash does not create a snapshot, changed text creates a snapshot, below-sensitivity change does not create a snapshot. Use a temporary SQLite file for tests.

When done tell me the manual test steps. Update PROGRESS.md.
```

**Verify:**
1. Start testsite (`python testsite/app.py`) and app (`python run.py`).
2. Add monitor for `http://127.0.0.1:5001/` with sensitivity medium. Click Check now. After ~10 seconds the status should be OK and one snapshot exists.
3. Click Check now again. Timestamp, banner, counter and token changed on the page, but there must still be ONE snapshot (noise filtered). If a new snapshot appears, copy the two stored text files and tell the agent: "these two texts differ only by noise, here is the diff, fix normalizer.py and add a test".
4. Visit `http://127.0.0.1:5001/set-price/499` then `http://127.0.0.1:5001/set-price/459`, click Check now: now a second snapshot must appear.
5. Add a second monitor with the same URL and a different name, click Check now: only ONE fetch should happen (check `jobs` table has one job) but both monitors update.
6. `pytest -q` passes.

---

## STEP 6: Failure handling + polite crawling

**Paste this:**

```
Read PLAN.md sections 5.6 and 5.7 carefully. Follow section 0.

TASK (Step 6 only): failure classification and rate limiting.

1. pagewatch/failures.py: classify_fetch(fetch_result) -> dict(outcome in "ok", "error", "blocked", message). Implement every rule from PLAN.md 5.6 (HTTP status rules, captcha/cloudflare text markers list as a constant, empty page rule). Pure function, easy to test.
2. pagewatch/ratelimit.py:
   - wait_for_domain(domain): ensures at least DOMAIN_DELAY_SECONDS between two fetches to the same domain (keep last fetch time per domain in memory; also ok to read urls.last_fetched_at after restart). The worker calls this before fetching. Sleep in small chunks so stop() stays responsive.
   - is_allowed_by_robots(url): uses urllib.robotparser, fetches robots.txt with requests (timeout 5 seconds, user-agent PageWatchBot), caches per domain for 24 hours, if robots.txt is missing or unreachable then ALLOW. For localhost/127.0.0.1 test URLs skip robots checks (config ROBOTS_SKIP_LOCALHOST=True).
   - apply_backoff(url_id, retry_after_header): on 429/503 set the URL's next allowed fetch time using Retry-After or doubling delay (max 24 hours). Store this in a new column urls.blocked_until (add it to create_tables with a safe ALTER TABLE migration so my existing database keeps working).
3. Update the worker: before fetching, check robots (if disallowed: mark all monitors of that URL as blocked with message "robots.txt disallows this URL" and finish the job without fetching), check blocked_until, then wait_for_domain. After fetching, run classify_fetch. If outcome is not ok: DO NOT call the content comparison, DO NOT create a snapshot. Update every attached monitor: status, status_message, consecutive_failures + 1, check_log row with outcome error/blocked, last_checked_at, next_check_at. If ok: reset consecutive_failures to 0.
   Playwright timeouts should result in retry by the job queue (fail_job), but after final failure monitors get status error.
4. Add jitter (random 0 to 60 seconds) when computing next_check_at in checker.py.
5. Dashboard: show status_message under the status dot (small text).
6. Tests: tests/test_failures.py covering 200 normal, 500, 403, 429, captcha text, cloudflare text, empty page, timeout error_type, and tests/test_ratelimit.py for the delay logic (mock time) and robots allow/deny parsing using a robots.txt text string.

Do not build alerts yet; leave a comment where the "site down" alert will be triggered after 3 consecutive failures.
When done give me manual test steps. Update PROGRESS.md.
```

**Verify:** add monitors for `/captcha`, `/down`, `/slow` on the test site, click Check now for each:
- `/captcha` becomes **blocked**, no snapshot.
- `/down` becomes **error**, no snapshot.
- `/slow` retries (check `jobs.attempts` increasing) and ends as error after ~3 tries.
- A normal page afterwards still works. Run `pytest -q`.

---

## STEP 7: Scheduler (automatic checks, one job per URL)

**Paste this:**

```
Read PLAN.md sections 5.2 and 5.3. Follow section 0.

TASK (Step 7 only): automatic periodic checks.

1. pagewatch/scheduler.py using APScheduler BackgroundScheduler. One interval job every 30 seconds named scheduler_tick:
   - reset_stuck_jobs()
   - select all active monitors where next_check_at <= now, GROUP BY url_id, and call enqueue_job(url_id) once per URL (the enqueue function already refuses duplicates).
   - Never run Playwright here.
   Provide start_scheduler() and stop_scheduler(). In init(): start the scheduler after the worker (replace the STEP 7 comment).
2. When a monitor is created or edited, set next_check_at = now so the first check happens soon.
3. When the 30s tick finds monitors due for the same URL with different intervals, only monitors actually due get their check_log/next_check_at updated, but the page is fetched once. Make sure the worker only runs check_monitor for monitors whose next_check_at <= now OR that were explicitly requested by "Check now". To support this, add an optional column jobs.monitor_id (NULL = all due monitors for the URL, set = only that monitor). Add via safe ALTER TABLE.
4. A small status panel on the dashboard footer: scheduler running yes/no, queued jobs count, running jobs count, failed jobs count in the last 24 hours.
5. Add a config flag DEV_FAST_MODE (env). When true, the interval dropdown also allows 1 minute and 2 minutes, and DOMAIN_DELAY_SECONDS becomes 2, so I can demo without waiting 15 minutes. Default false. Clearly comment that this is for demos only and mention it in README later.
6. Tests: tests/test_scheduler.py: 3 monitors on the same URL produce exactly 1 queued job; a monitor not yet due produces none; stuck job reset works.

When done give me manual test steps. Update PROGRESS.md.
```

**Verify:** set `DEV_FAST_MODE=true` in `.env`. Add 3 monitors for the same test-site URL with interval 1 minute. Restart app. Within ~2 minutes check the `jobs` table: ONE job per cycle, not three. Change price on the test site and see a new snapshot appear automatically. Restart the app while a job runs and confirm nothing stays stuck.

---

## STEP 8: Diffs, version timeline and compare page

**Paste this:**

```
Read PLAN.md section 5.9. Follow section 0. No JavaScript.

TASK (Step 8 only): diffs and comparison UI.

1. pagewatch/differ.py:
   - text_diff_lines(old_text, new_text) -> list of (kind, text) with kind in "same", "added", "removed" using difflib.
   - side_by_side_html(old_text, new_text) -> HTML string using difflib.HtmlDiff (make_table, context=True, numlines=3) with safe escaping. Pico.css may fight with its table styles, so add a small CSS block in a <style> tag in the compare template to keep colours readable (green added, red removed, yellow changed) in light and dark mode.
2. pagewatch/imgdiff.py:
   - make_diff_image(old_png_path, new_png_path, out_path): open both with Pillow, pad the smaller one with white so sizes match, compute ImageChops.difference, threshold small differences (ignore tiny anti-aliasing noise), find changed rows/columns blocks, draw red rectangles (3px) around changed regions on a copy of the NEW screenshot, save PNG. Return the percentage of changed pixels. Keep the algorithm simple: divide the image into 40x40 pixel tiles, mark a tile changed if more than 2 percent of its pixels differ, merge neighbouring changed tiles into rectangles. Comment each step in plain English.
   - Cache diff images in data/diffs/ named diff_<a>_<b>.png so they are not recomputed.
3. Routes and templates:
   - /monitor/<id> becomes the version timeline: a vertical list of snapshots newest first (date, hash prefix, "+x/-y lines vs previous", small screenshot thumbnail using CSS width only), each linking to /monitor/<id>/compare?a=<previous>&b=<this>.
   - /monitor/<id>/compare?a=<id>&b=<id>: dropdowns to pick ANY two snapshots of this monitor (a plain GET form, no JS), then shows: (1) the unified coloured text diff, (2) the side-by-side table, (3) old and new screenshots next to each other, (4) the highlighted diff screenshot and "x percent of the page changed".
   - Validate that both snapshots belong to this monitor, show a friendly message if the text file is missing.
4. Serve files from data/ only through a route that checks the path stays inside data/ (no path traversal). Add a test for that.
5. Tests: tests/test_differ.py (added/removed detection), tests/test_imgdiff.py (create two tiny images with Pillow where one has a red square, assert it produces a changed percentage > 0 and identical images give 0).

When done give me manual test steps. Update PROGRESS.md.
```

**Verify:** on the test site change the price twice, and the paragraph once (`/set-text/hello-world-new-text`). Open a monitor timeline: 3 or 4 snapshots appear. Compare first vs last: coloured diff shows the price line changed, screenshot diff has red boxes around the changed areas. `pytest -q` passes.

---

## STEP 9: Alerts (email, Telegram, Discord) + dedupe + digest

**Paste this:**

```
Read PLAN.md section 5.8. Follow section 0.

TASK (Step 9 only): alerts.

1. pagewatch/summary.py: make_summary(old_text, new_text) -> one line string, rule-based (no AI): if the two texts differ mostly by one number, say "Number changed from 499 to 459"; otherwise "3 lines added, 1 removed". Include up to 2 short examples of added/removed lines trimmed to 80 characters. Tests in tests/test_summary.py.
2. pagewatch/alerts.py:
   - send_email(to, subject, body): smtplib with settings from config (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, use STARTTLS). If SMTP is not configured, log "email skipped (not configured)" and return False.
   - send_telegram(chat_id, text): requests.post to the Telegram Bot API sendMessage endpoint using TELEGRAM_BOT_TOKEN, timeout 10 seconds.
   - send_discord(webhook_url, text): requests.post JSON {"content": text}, timeout 10 seconds.
   - notify_change(monitor, old_snapshot, new_snapshot, summary): builds the message (monitor name, URL, summary, time, diff link = BASE_URL + /monitor/<id>/compare?a=<old>&b=<new>) and sends on every channel configured for that monitor. BEFORE sending each channel, INSERT into alerts with dedupe_key f"{monitor_id}:{snapshot_id}:{channel}"; if the insert violates UNIQUE, skip that channel silently. Never raise exceptions out of this module (catch, log, continue).
   - notify_status(monitor, kind, message) for "down/blocked" (after 3 consecutive failures, only once until it recovers) and "recovered". Use dedupe keys including the kind and a failure-episode marker so we do not spam.
   - Do not alert for the baseline (first) snapshot.
   - Do not alert if monitor.is_noisy = 1 (noisy guard from PLAN.md 5.5 point 6; implement the noisy_streak logic in checker.py now if not done: 5 consecutive changes sets is_noisy=1, any unchanged check resets streak and clears is_noisy).
   - Keyword rule: if monitor.keyword is set, only alert when the keyword's presence changed (appeared or disappeared) between old and new text (case-insensitive). The snapshot is still stored.
   - If monitor.daily_digest = 1, skip instant alerts (digest handles it).
3. Hook notify_change and notify_status into checker.py / worker.py at the right places (replace the earlier comment).
4. pagewatch/digest.py: build_digest_for_monitor(monitor, since) and send_daily_digests(): for monitors with daily_digest=1, collect changes in the last 24 hours and send ONE message per monitor (if there were changes). Schedule it in scheduler.py as a cron job at 09:00 local time. Also add a hidden route /admin/send-digest-now (POST, only works when DEV_FAST_MODE is true) for demo.
5. Monitor detail page: add a "Send test alert" button which sends a harmless test message to the configured channels (no dedupe for test messages).
6. Tests with mocked senders (no network): a change triggers exactly one alert per channel; triggering twice for the same snapshot sends nothing the second time; baseline sends nothing; noisy monitor sends nothing; keyword rule works; down alert after 3 failures only once.
7. Document how to create a Telegram bot token and a Discord webhook in comments at the top of alerts.py, and add all keys to .env.example.

When done give me manual test steps. Update PROGRESS.md.
```

**Verify:** create a Discord server with a webhook (Server Settings, Integrations, Webhooks), paste the URL in the monitor, click "Send test alert". Change price on the test site and check; exactly one Discord message arrives. Trigger the same check again: no duplicate. Use `/always-different` as a monitor on `high` sensitivity: after 5 changes it becomes noisy and alerts stop. Telegram: talk to @BotFather, create a bot, put token in `.env`, send a message to the bot, get your chat id from the agent's instructions.

---

## STEP 10: Core requirements audit (stop adding features)

**Paste this:**

```
Read PLAN.md fully. Follow section 0.

TASK (Step 10 only): audit, do NOT add new features.

1. Go through the 8 core requirements and the 4 design questions in PLAN.md one by one. For each, tell me: DONE / PARTIAL / MISSING, which file and function implements it, and how I can demonstrate it in the UI.
2. Run pytest and report results. Fix failing tests or obvious bugs you find, but tell me what you changed.
3. Check these edge cases by reading the code and tell me honestly if each is handled: app restart while a job is running; two monitors with same URL but different selectors; deleting a monitor that has snapshots (must also delete its files and rows, add that if missing); a URL that redirects; a very large page (limit stored text to 1 MB and say so); two quick "Check now" clicks (must create one job); worker thread crash (it must restart or log clearly).
4. Make sure no secret is printed in logs and .env is gitignored.
5. Write the findings as a table. Do not rewrite big parts of the code.
Update PROGRESS.md with remaining gaps.
```

Then fix the gaps one at a time using the Fix prompt below. **Commit.** At this point the core project is complete.

---

## STEP 11: Bonus features (only if Step 10 is clean)

Do these as three separate prompts, in this order. Commit after each.

### 11a: Number tracking with chart

```
Read PLAN.md. Follow section 0.
TASK: number tracking.
1. numbers.py: if monitor.number_selector is set, after each OK fetch extract the first number from the element matching that selector (handle "₹1,299.50", "$ 499", "1,23,456" Indian format, "4.5 stars") and insert into number_points (also on unchanged checks, so the chart has regular points). Pure function parse_number(text) -> float or None with tests for at least 10 formats.
2. Chart: route /monitor/<id>/chart.png that draws a line chart with matplotlib (use the Agg backend, no GUI) of the last 200 points, with date on x axis and a title. Show it on the monitor detail page when number tracking is on.
3. Optional threshold alert: add monitor fields number_alert_below and number_alert_above (safe ALTER TABLE, optional inputs in the form); if the value crosses a threshold, send an alert through the existing alerts module with a dedupe key per snapshot/value.
Tests for parse_number and threshold logic. Update PROGRESS.md.
```
Verify: add a number selector for the price element of the test site (ask the agent for the right CSS selector from the test page), change price a few times, see the chart.

### 11b: Per-page RSS feed

```
Read PLAN.md. Follow section 0.
TASK: per-page RSS. feeds.py builds RSS 2.0 XML by hand with xml.etree.ElementTree (no new libraries) for a monitor: channel title = monitor name, link = monitor page, one item per snapshot (latest 50) with title = summary of change, pubDate, guid = snapshot id, description = summary + link to compare page. Route /monitor/<id>/feed.xml with content type application/rss+xml. Add a visible "RSS" link on the monitor page and a <link rel="alternate"> tag in the page head. Store each snapshot's summary in a new column snapshots.summary (safe ALTER TABLE, filled in by checker.py using make_summary). Tests: XML is valid and contains the right number of items.
Update PROGRESS.md.
```

### 11c: Better summaries (still no AI)

```
Read PLAN.md. Follow section 0.
TASK: improve summary.py. Handle: price/number change with percent change ("Price dropped from 499 to 459 (-8.0%)"), a new section appearing, a keyword appearing or disappearing, "Out of stock" / "In stock" phrase flips. Keep it rule-based, deterministic and tested. Show the summary on the timeline and in alerts. Add tests.
Update PROGRESS.md.
```

Skip the browser extension and AI summaries unless you have days to spare. A rule-based summary that works beats an AI call that fails during the demo.

---

## STEP 12: README with the 4 design answers + measurements

**Paste this:**

```
Read PLAN.md fully, especially sections 7 and 8. Follow section 0.

TASK (Step 12 only): write README.md.

1. Follow the 8 sections listed in PLAN.md section 7.
2. For the 4 design questions, write short, concrete answers in plain English (no buzzwords), each ending with "Implemented in: <file/function>". Base answers on what the code REALLY does (check the code, do not copy PLAN.md blindly).
3. Create scripts/measure.py that runs the real pipeline against the test site: performs 20 checks of the unchanged page and 5 of a changed page, records duration per check, and prints average, median and max in milliseconds, plus how many snapshots were created (should be tiny) and how many fetches happened for 5 monitors on the same URL (should be 1 per cycle). Run it, and put the REAL numbers in the README. Do not invent numbers. If something fails, tell me.
4. Add a "Demo script" section: a numbered list of what to click, in order, for a 5 minute live demo (using the test site).
5. Add a failure-handling table (outage, CAPTCHA, timeout, robots.txt, noisy page, selector matches nothing) with what status shows and whether an alert is sent.
6. Add a short "Known limitations" section, honest.
Update PROGRESS.md.
```

**Verify:** a person who has never seen the project should be able to follow the README from zero. Test it yourself: clone the repo to a new folder, create a fresh venv, follow the README exactly.

---

## STEP 13 (OPTIONAL): Visual region picker

Only attempt this if Steps 1 to 12 are done, committed and demo-ready. Create a git branch first: `git checkout -b picker`. If it goes badly, switch back with `git checkout master` (or `main`, whichever `git branch` shows) and nothing is lost.

**Paste this:**

```
Read PLAN.md fully. Follow section 0 (this step is the only exception allowed to use JavaScript, keep it under 80 lines, comment every line in simple English, no frameworks).

TASK: visual picker for include/ignore regions.

Approach (server renders, browser only clicks):
1. New page /monitor/<id>/picker. The server uses the worker thread (via a new job type "picker_snapshot", do NOT call Playwright from Flask directly) to render the page and save: a full-page screenshot, and a JSON list of up to 300 visible elements, each with a unique CSS selector (prefer id, then data attributes, then a short class based path, then nth-of-type path), and its bounding box (x, y, width, height) measured via JS evaluate in Playwright.
2. The picker page shows the screenshot in a div with position: relative and draws transparent boxes (absolutely positioned div overlays) for each element. Hovering highlights a box, clicking a box shows its selector and two buttons: "Watch this region" and "Ignore this region". A tiny JS function posts the choice to a Flask route that appends the selector to include_selectors or ignore_selectors of the monitor.
3. Show current include/ignore selectors on the page with a remove button for each (plain HTML form posts).
4. If the picker snapshot is not ready yet, show "Preparing page... refresh in a few seconds" (no polling JS, a meta refresh tag is fine).
5. Keep the text-box version of selectors working as it is.
Tests: selector generation function tested on a small HTML string (unique selector for an element with id, without id).
Update PROGRESS.md.
```

Merge only if it works end to end: switch back to your original branch (`git checkout master` or `main`) and run `git merge picker`.

---

## Helper prompts (use any time)

**Fix prompt** (when something fails):
```
Something fails. Here is exactly what I did and what I saw.
Command or click: <paste>
Full error message or wrong behaviour: <paste full text, not a summary>
Expected: <what you expected>
First explain the cause in simple Hinglish in 3 lines. Then fix it with the smallest possible change. Do not refactor unrelated code. Tell me which files you changed and re-run the relevant tests.
```

**Explain prompt** (understand before moving on):
```
Explain <file or function> to me like I am a beginner who only knows class-level Python. Go line by line for the important parts, use a small example input and output, and tell me what would break if I deleted it. Do not change any code.
```

**Stuck / drifting prompt** (agent starts doing too much):
```
Stop. You are doing more than the current step. Re-read PLAN.md sections 0 and 9. Revert anything outside the current step (list what you will revert before doing it), then continue with only the current step.
```

**Review prompt** (before every commit if you have time):
```
Review the code you just wrote against PLAN.md. List: (1) anything that violates the plan, (2) anything that will break an already existing database file (missing migrations), (3) anything that could crash the worker thread, (4) functions longer than 40 lines that should be split. Do not change code, only report.
```

**Context reset prompt** (new chat, agent forgot everything):
```
Read PLAN.md and PROGRESS.md. Summarise in 10 lines where the project stands, then wait for my instruction. Do not write code yet.
```

---

## Honest risk notes

- Playwright threading is the #1 thing agents get wrong. If you see Playwright being called from a Flask route, use the Stuck prompt immediately.
- Noise filtering is never perfect on real sites. Demo on your own test site, and show one real site (like a simple news page or example.com) only as a bonus.
- Do not demo the email channel unless you tested SMTP beforehand. Discord webhook is the most reliable alert for a live demo.
- Read every diff the agent produces at least once, even quickly. If a judge asks "how does X work", "the agent wrote it" is the worst answer.
