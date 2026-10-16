# PageWatch: Website Change Detector (PLAN.md)

This file is the single source of truth. Read it fully before writing any code. If a request in chat conflicts with this file, ask me before deviating.

## 0. About the developer (read this first)

- I am a beginner. I only know basic Python (class level). I do NOT know JavaScript and I am weak at web development.
- Write simple, readable Python. No clever one-liners, no metaclasses, no decorators beyond what Flask needs, no async/await.
- Every file starts with a short comment block: what this file does, and which other files it talks to.
- Every function has a 1 to 3 line docstring in plain English.
- Use clear function names (`fetch_page`, `normalize_text`, `save_snapshot`), not abbreviations.
- Avoid JavaScript entirely, except in the optional last step (visual picker), and there keep it under 80 lines, heavily commented.
- Do not add libraries that are not listed in section 2 without asking me first.
- After finishing any step, explain in simple words (Hinglish is fine) what you built and how to run and test it.

## 1. Goal

Build a service that monitors public web pages and alerts users to meaningful changes while ignoring noise.

### Core requirements (all 8 must work)

1. Users add a URL, a name and a check interval (15 min to 24 h). Pages render in a headless browser (Playwright).
2. Checks run through a scheduler and a job queue with timeouts and retries. Public pages only, no stored credentials.
3. Each check saves page text and a screenshot. A new snapshot is stored ONLY when the content hash changes.
4. Noise filtering for timestamps, counters, ads, rotating banners and random tokens, plus a sensitivity setting.
5. Region selection: regions to watch and regions to ignore, saved as CSS selectors.
6. Text diff, highlighted screenshot diff, and side-by-side comparison of any two versions.
7. Alerts via email and Telegram/Discord webhook with a summary and a diff link. No duplicate alerts. Optional daily digest.
8. Per-page version timeline and a dashboard with last checked, last changed and status (OK, error, blocked).

### Design questions (answers go in README.md, see section 7)

1. Is a site outage or CAPTCHA a change?
2. If 200 users watch the same URL, is it fetched 200 times?
3. How to avoid endless alerts on pages that differ on every load?
4. How to avoid hammering a site with requests?

### Bonus items (only after core is finished and tested)

- Keyword-only alerts
- Number tracking with a chart
- One-line change summaries (rule-based first; AI optional later)
- Per-page RSS feed
- Browser extension: SKIP unless everything else is done

## 2. Tech stack (fixed)

| Purpose | Choice |
|---|---|
| Language | Python 3.11 or newer |
| Web framework | Flask (server-rendered HTML with Jinja templates, no JS framework) |
| Browser rendering | Playwright for Python, sync API, Chromium |
| Database | SQLite via built-in `sqlite3` (no ORM) |
| Scheduler | APScheduler (BackgroundScheduler) |
| Job queue | Own simple queue backed by the `jobs` table in SQLite. NO Redis, NO Celery |
| Text diff | built-in `difflib` |
| Screenshot diff | Pillow (`PIL.ImageChops`) |
| HTTP calls (webhooks) | `requests` |
| Email | built-in `smtplib` |
| Charts | matplotlib (render PNG on the server) |
| Styling | Pico.css loaded from CDN (one `<link>` tag), no custom CSS framework |
| Tests | pytest |
| Config | `.env` file read with `python-dotenv` |

## 3. Folder structure

```
pagewatch/
  PLAN.md
  PROGRESS.md              (agent keeps this updated after every step)
  README.md                (final deliverable, see section 7)
  requirements.txt
  .env.example
  .gitignore
  run.py                   (starts the app: calls init() and app.run)
  pagewatch/
    __init__.py            (init(): the ONE place where every feature is hooked in)
    config.py              (reads .env, holds all constants)
    db.py                  (connection helper, create_tables(), small query helpers)
    fetcher.py             (Playwright: render page, return text/html/screenshot/status)
    normalizer.py          (noise filtering, selector include/ignore, hashing)
    checker.py             (the pipeline for one monitor: fetch -> normalize -> compare -> save)
    failures.py            (classify outage / CAPTCHA / blocked / timeout)
    jobqueue.py            (enqueue, claim, retry with backoff, timeout)
    worker.py              (the single thread that owns Playwright and runs jobs)
    scheduler.py           (APScheduler: finds due monitors, enqueues one job per URL)
    ratelimit.py           (per-domain delay + robots.txt check)
    differ.py              (text diff, HTML side-by-side)
    imgdiff.py             (screenshot diff with red highlight boxes)
    alerts.py              (email, Telegram, Discord, dedupe)
    digest.py              (daily digest)
    summary.py             (one-line change summary)
    numbers.py             (number tracking + chart)
    feeds.py               (per-page RSS)
    web/
      routes.py            (Flask routes only, no business logic)
      templates/           (base.html, dashboard.html, add_monitor.html, monitor.html, compare.html, ...)
  testsite/
    app.py                 (my own local fake website with price, timestamp, rotating banner, random token, counter, /captcha, /down)
  tests/
  data/                    (gitignored: pagewatch.db, screenshots/, texts/)
```

## 4. Database schema

Use these exact tables. Create them in `db.create_tables()`. Use `CREATE TABLE IF NOT EXISTS`. Store datetimes as ISO strings in UTC.

```
urls          (id, url UNIQUE, domain, last_fetched_at, last_http_status, consecutive_failures)
monitors      (id, name, url_id -> urls.id, interval_minutes, sensitivity,        -- 'low' | 'medium' | 'high'
               include_selectors,     -- text, one CSS selector per line, empty = whole page
               ignore_selectors,      -- text, one CSS selector per line
               keyword,               -- optional, alert only if this word appears/disappears
               number_selector,       -- optional, CSS selector of a number to track
               alert_email, telegram_chat_id, discord_webhook_url,
               daily_digest,          -- 0 or 1
               status,                -- 'pending' | 'ok' | 'error' | 'blocked'
               status_message,
               last_checked_at, last_changed_at, next_check_at,
               noisy_streak,          -- consecutive checks that changed
               is_noisy,              -- 0 or 1
               consecutive_failures,
               is_active, created_at)
snapshots     (id, monitor_id, taken_at, content_hash, text_path, screenshot_path, text_length)
jobs          (id, url_id, status,    -- 'queued' | 'running' | 'done' | 'failed'
               attempts, run_after, created_at, started_at, finished_at, error)
check_log     (id, monitor_id, checked_at, outcome,   -- 'unchanged' | 'changed' | 'blocked' | 'error'
               message, http_status, duration_ms)
alerts        (id, monitor_id, snapshot_id, channel, dedupe_key UNIQUE, summary, sent_at)
number_points (id, monitor_id, snapshot_id, value REAL, taken_at)
```

Text and screenshots are stored as files under `data/` (paths saved in DB), not as blobs.

## 5. Behaviour rules (these answer the hidden requirements)

### 5.1 Threading rule (very important)
Playwright sync objects only work in the thread that created them. Therefore:
- Exactly ONE worker thread (`worker.py`) creates the Playwright browser and runs all fetches.
- Flask routes and the scheduler NEVER call Playwright. They only add rows to the `jobs` table.
- "Check now" button = enqueue a job.

### 5.2 One fetch per URL, many monitors (design question 2)
- `urls` has one row per unique normalized URL. `monitors` points to it.
- The scheduler groups due monitors by `url_id` and enqueues ONE job per URL.
- The worker renders the page once, then runs the checker for EVERY monitor attached to that URL (each applies its own include/ignore selectors, sensitivity, keyword).
- Normalize URLs before storing (lowercase host, strip fragment `#...`, strip trailing slash).
- There is no login system in this project. Each monitor stores its own alert destinations. Note this in README as a known simplification.

### 5.3 Job queue, timeouts, retries
- Job timeout: 45 seconds for the page render. Use Playwright's own timeout and also a hard guard.
- Retries: up to 3 attempts. Backoff: 1 min, 2 min, 4 min (`run_after` column).
- A job stuck in `running` for more than 5 minutes is reset to `queued` at startup and every scheduler tick.
- Only one job per URL may be queued or running at a time.

### 5.4 Snapshots (requirement 3)
- Pipeline per monitor: take the rendered page, apply include/ignore selectors, extract visible text, normalize, hash with SHA-256.
- If the hash equals the latest snapshot hash: only update `last_checked_at`, write a `check_log` row, do NOT store anything.
- If different: save text file + screenshot, insert a `snapshots` row, update `last_changed_at`.
- The very first check creates the baseline snapshot and sends NO alert.

### 5.5 Noise filtering (requirement 4, design question 3)
Done in `normalizer.py` on the text, before hashing:
1. Remove `script`, `style`, `noscript`, `iframe`, `svg` text.
2. Remove elements matching a built-in ad selector list (`[id*="ad-"]`, `[class*="advert"]`, `[class*="banner"]`, `[class*="cookie"]`, `.ads`, `ins.adsbygoogle`, etc.), plus the monitor's ignore selectors.
3. Regex-replace with placeholders: ISO dates and times, `12:45:10`, `Oct 16, 2026`, `16/10/2026`, "x minutes ago", "Updated ...", counters like `1,234 views` / `5 comments` / `3 online`, long random tokens (hex or base64 strings of 16+ chars, UUIDs).
4. Collapse whitespace, drop empty lines.
5. Sensitivity, applied when deciding if a hash change is "meaningful":
   - `high`: any change in normalized text counts.
   - `medium`: counts only if at least 2 percent of lines changed (or at least 1 line added/removed in text under 50 lines).
   - `low`: counts only if at least 10 percent of lines changed.
   A change below the threshold is logged as `unchanged` with message "below sensitivity" and no new snapshot is stored.
6. Endless-change guard: if a monitor changes on 5 consecutive checks, set `is_noisy = 1`, stop sending alerts for it, and show a warning on the dashboard: "This page changes on every load. Add ignore regions or lower sensitivity." Reset `noisy_streak` after any unchanged check.

### 5.6 Failure handling (design question 1)
`failures.py` classifies a fetch result BEFORE comparing content:
- HTTP status 400 or above, DNS error, connection error, timeout: outcome `error`.
- HTTP 403/429/503, or page text contains markers like "captcha", "verify you are human", "access denied", "unusual traffic", "just a moment" (Cloudflare), "enable javascript and cookies": outcome `blocked`.
- Rendered text shorter than 20 characters: outcome `error` ("empty page").
- For any of these: do NOT store a snapshot, do NOT treat it as a change. Update monitor `status` and `status_message`.
- Only after 3 consecutive failures send one "site down / blocked" alert (type `status`). Send a "recovered" alert when it works again. Never send a "content changed" alert for a failure page.

### 5.7 Being polite to websites (design question 4)
In `ratelimit.py`:
- Minimum monitor interval is 15 minutes (enforced in the form and in the backend).
- Per-domain delay: at least 10 seconds between two fetches to the same domain (configurable).
- Check robots.txt with `urllib.robotparser` before the first fetch of a domain (cache 24 hours). If disallowed: status `blocked`, message "robots.txt disallows this URL".
- Send an honest User-Agent: `PageWatchBot/1.0 (+student project)`.
- On HTTP 429 or 503: respect `Retry-After` if present, otherwise double that URL's next delay (max 24 h).
- Add random jitter (0 to 60 seconds) to `next_check_at` so many monitors do not fire at the same instant.

### 5.8 Alerts (requirement 7)
- Channels: email (SMTP settings in `.env`), Telegram (bot token in `.env`, chat id per monitor), Discord (webhook URL per monitor).
- Alert content: monitor name, URL, one-line summary, time, and a link to `/monitor/<id>/compare?a=<old_snapshot>&b=<new_snapshot>`. The base URL comes from `.env` (`BASE_URL`).
- Dedupe: `dedupe_key = f"{monitor_id}:{snapshot_id}:{channel}"`, UNIQUE in `alerts`. Insert first, send after. If insert fails, skip.
- Daily digest: if `daily_digest = 1`, do not send instant alerts. Instead one message per day at 09:00 with all changes of the last 24 hours.
- Alert sending failures must never crash the worker. Log and continue.

### 5.9 Diffs (requirement 6)
- Text diff: `difflib`, shown with added lines green and removed lines red.
- Compare page: choose any two snapshots of the same monitor, show side-by-side text (`difflib.HtmlDiff` is acceptable) and both screenshots next to each other.
- Screenshot diff: Pillow. If sizes differ, pad the smaller one. Compute per-pixel difference, find changed areas, draw red rectangles on the NEW screenshot, save as `diff_<a>_<b>.png` under `data/`.

## 6. Local test website (`testsite/app.py`)

A tiny Flask app on port 5001 that I control. It must have:
- `/` : a product page with a price I can change by visiting `/set-price/<n>`, a live timestamp, a rotating banner (changes each load), a random token in a hidden-looking text, a "1,234 views" counter that increases each load, and a real paragraph of stable text I can edit by `/set-text/<words>`.
- `/captcha` : returns a page saying "Please verify you are human (captcha)".
- `/down` : returns HTTP 500.
- `/slow` : sleeps 60 seconds (to test timeouts).
- `/always-different` : content totally different on every load.

## 7. README.md (final deliverable) must contain

1. What it is, screenshots placeholder list.
2. Setup and run instructions (Windows PowerShell commands).
3. Architecture diagram in text (boxes and arrows) and a short explanation of each module.
4. Answers to the 4 design questions, concrete and short, pointing to the module that implements each.
5. Latency/behaviour notes: how long one check takes on the test site (measure and write real numbers), timeouts, retries.
6. Test conditions and failure handling table (outage, CAPTCHA, timeout, robots.txt, noisy page).
7. Known limitations (no login system, single worker thread, SQLite).
8. How to run tests.

## 8. Definition of done

- All 8 core requirements demonstrably work against `testsite`.
- `pytest` passes.
- README complete with real measured numbers.
- Fresh clone + README instructions = app runs.
- No secrets committed (`.env` in `.gitignore`).

## 9. Working agreement for every step

1. Before coding, reply with a SHORT plan (bullet points) and wait if anything in this file is unclear.
2. Only do the current step. Do not build features from later steps.
3. After coding: tell me exactly which commands to run to test, and what output I should see.
4. Update `PROGRESS.md` (what is done, what is next, known bugs).
5. Never delete or rewrite files from earlier steps unless the current step requires it, and tell me if you do.
