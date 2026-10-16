from urllib.parse import urlparse, urlunparse
from pagewatch import config


def normalize_url(raw_url):
    if not raw_url or not isinstance(raw_url, str) or not raw_url.strip():
        raise ValueError("URL cannot be empty.")

    url = raw_url.strip()
    parsed = urlparse(url)

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a valid website address.")

    hostname = hostname.lower()
    is_local = hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
    if is_local and not config.ALLOW_LOCALHOST:
        raise ValueError("Monitoring localhost or internal addresses is not allowed.")

    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    else:
        netloc = hostname

    path = parsed.path
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
    elif path == "/":
        path = ""

    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))


def get_domain(url):
    try:
        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname.lower()
    except Exception:
        pass
    return ""
