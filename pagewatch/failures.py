BLOCKED_MARKERS = [
    "captcha",
    "verify you are human",
    "access denied",
    "unusual traffic",
    "just a moment",
    "enable javascript and cookies",
]


def classify_fetch(fetch_result):
    if not isinstance(fetch_result, dict):
        return {"outcome": "error", "message": "invalid fetch result"}

    error_type = fetch_result.get("error_type")
    error_message = fetch_result.get("error_message") or ""

    if error_type == "timeout":
        return {"outcome": "error", "message": error_message or "timeout"}

    if error_type in ("dns", "connection"):
        return {"outcome": "error", "message": error_message or f"network error ({error_type})"}

    if not fetch_result.get("ok"):
        return {"outcome": "error", "message": error_message or "fetch failed"}

    http_status = fetch_result.get("http_status")
    if http_status is not None:
        if http_status in (403, 429, 503):
            return {"outcome": "blocked", "message": f"HTTP {http_status} blocked"}
        if http_status >= 400:
            return {"outcome": "error", "message": f"HTTP {http_status} error"}

    page_text = fetch_result.get("page_text") or ""
    html = fetch_result.get("html") or ""
    content_lower = (page_text + " " + html).lower()

    for marker in BLOCKED_MARKERS:
        if marker in content_lower:
            return {"outcome": "blocked", "message": f"blocked marker: {marker}"}

    stripped_text = page_text.strip()
    if len(stripped_text) < 20:
        return {"outcome": "error", "message": f"Empty page ({len(stripped_text)} chars)"}

    return {"outcome": "ok", "message": ""}
