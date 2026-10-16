import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

USER_AGENT = "PageWatchBot/1.0 (+student project)"
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800
NETWORK_IDLE_WAIT_MS = 5000


class BrowserSession:
    def __init__(self):
        self._playwright = None
        self._browser = None

    def start(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)

    def stop(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def fetch_page(self, url, timeout_seconds=45, ignore_selectors=None):
        start_time = time.time()
        result = {
            "ok": False,
            "http_status": None,
            "final_url": url,
            "html": "",
            "page_text": "",
            "screenshot_bytes": b"",
            "error_type": None,
            "error_message": None,
            "duration_ms": 0,
        }

        timeout_ms = timeout_seconds * 1000
        context = None
        page = None

        try:
            # clean context per fetch
            context = self._browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            )
            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            response = page.goto(url, wait_until="load", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_WAIT_MS)
            except PlaywrightTimeout:
                pass

            if response is not None:
                result["http_status"] = response.status

            result["final_url"] = page.url
            result["html"] = page.content()
            result["page_text"] = page.evaluate("() => document.body.innerText")
            result["screenshot_bytes"] = page.screenshot(full_page=True)
            result["ok"] = True

        except PlaywrightTimeout:
            result["error_type"] = "timeout"
            result["error_message"] = "timeout"

        except Exception as err:
            error_text = str(err).lower()
            if "net::err_name_not_resolved" in error_text:
                result["error_type"] = "dns"
                result["error_message"] = "dns error"
            elif "net::err_connection_refused" in error_text:
                result["error_type"] = "connection"
                result["error_message"] = "connection refused"
            elif "net::err_connection_timed_out" in error_text:
                result["error_type"] = "timeout"
                result["error_message"] = "connection timed out"
            elif "net::err_" in error_text:
                result["error_type"] = "connection"
                result["error_message"] = "network error: " + str(err)[:200]
            else:
                result["error_type"] = "other"
                result["error_message"] = "unexpected error: " + str(err)[:200]

        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            result["duration_ms"] = int((time.time() - start_time) * 1000)

        return result
