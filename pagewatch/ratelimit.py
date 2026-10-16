import time
from urllib.parse import urlparse
import urllib.robotparser
from datetime import datetime, timezone, timedelta
import requests

from pagewatch import config
from pagewatch.db import run_query, run_write

_LAST_FETCH_TIMES = {}
_ROBOTS_CACHE = {}

ROBOTS_USER_AGENT = "PageWatchBot"
FULL_USER_AGENT = "PageWatchBot/1.0 (+student project)"
ROBOTS_CACHE_SECONDS = 24 * 60 * 60
MAX_BACKOFF_SECONDS = 24 * 60 * 60


def wait_for_domain(domain, is_running_callback=None):
    if not domain:
        return

    now = time.time()
    last_time = _LAST_FETCH_TIMES.get(domain)

    if last_time is None:
        rows = run_query(
            "SELECT MAX(last_fetched_at) AS last_dt FROM urls WHERE domain = ?",
            (domain,)
        )
        if rows and rows[0]["last_dt"]:
            try:
                dt = datetime.fromisoformat(rows[0]["last_dt"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                last_time = dt.timestamp()
            except Exception:
                last_time = 0.0
        else:
            last_time = 0.0

    elapsed = now - last_time
    wait_needed = config.DOMAIN_DELAY_SECONDS - elapsed

    if wait_needed > 0:
        remaining = wait_needed
        while remaining > 0:
            if is_running_callback and not is_running_callback():
                return
            sleep_chunk = min(remaining, 0.2)
            time.sleep(sleep_chunk)
            remaining -= sleep_chunk

    _LAST_FETCH_TIMES[domain] = time.time()


def parse_robots_txt(domain, robots_text):
    rp = urllib.robotparser.RobotFileParser()
    lines = robots_text.splitlines() if robots_text else []
    rp.parse(lines)
    _ROBOTS_CACHE[domain] = (rp, time.time())
    return rp


def is_allowed_by_robots(url):
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0") and config.ROBOTS_SKIP_LOCALHOST:
        return True

    domain = hostname
    if not domain:
        return True

    now = time.time()
    cached = _ROBOTS_CACHE.get(domain)
    if cached is not None:
        rp, fetch_time = cached
        if (now - fetch_time) < ROBOTS_CACHE_SECONDS:
            return rp.can_fetch(ROBOTS_USER_AGENT, url)

    port_part = f":{parsed.port}" if parsed.port else ""
    robots_url = f"{parsed.scheme}://{domain}{port_part}/robots.txt"

    rp = urllib.robotparser.RobotFileParser()
    try:
        resp = requests.get(robots_url, headers={"User-Agent": FULL_USER_AGENT}, timeout=5)
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
        else:
            rp.parse([])
    except Exception:
        # allow on network error / missing robots.txt
        rp.parse([])

    _ROBOTS_CACHE[domain] = (rp, now)
    return rp.can_fetch(ROBOTS_USER_AGENT, url)


def apply_backoff(url_id, retry_after_header=None):
    delay_seconds = None
    if retry_after_header:
        try:
            delay_seconds = int(str(retry_after_header).strip())
        except (ValueError, TypeError):
            delay_seconds = None

    if delay_seconds is None or delay_seconds <= 0:
        rows = run_query("SELECT consecutive_failures FROM urls WHERE id = ?", (url_id,))
        failures = rows[0]["consecutive_failures"] if rows else 0
        delay_seconds = 60 * (2 ** min(failures, 10))

    delay_seconds = min(delay_seconds, MAX_BACKOFF_SECONDS)
    blocked_until = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()

    run_write("UPDATE urls SET blocked_until = ? WHERE id = ?", (blocked_until, url_id))
    return blocked_until
