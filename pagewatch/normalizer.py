import re
import hashlib
import difflib
from bs4 import BeautifulSoup

from pagewatch.config import (
    SENSITIVITY_HIGH_PERCENT,
    SENSITIVITY_MEDIUM_PERCENT,
    SENSITIVITY_LOW_PERCENT,
    SHORT_TEXT_LINE_THRESHOLD,
)

RE_ISO_DATE = re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b")
RE_DMY_DATE = re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b")
MONTH_NAMES = (
    "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
    "|January|February|March|April|May|June|July"
    "|August|September|October|November|December"
)
RE_NAMED_DATE = re.compile(
    r"\b(?:" + MONTH_NAMES + r")\s+\d{1,2},?\s+\d{4}\b"
    r"|\b\d{1,2}\s+(?:" + MONTH_NAMES + r")\s+\d{4}\b",
    re.IGNORECASE,
)
RE_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\b")
RE_RELATIVE_TIME = re.compile(
    r"\b\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b"
    r"|\ba?\s*few\s+(?:second|minute|hour|day)s?\s+ago\b"
    r"|\bjust\s+now\b",
    re.IGNORECASE,
)
RE_UPDATED = re.compile(
    r"\b(?:last\s+)?updated\b(?:\s*:\s*|\s+(?:on|at|by|today|yesterday|recently)\b)?",
    re.IGNORECASE,
)
RE_COUNTER = re.compile(
    r"\b[\d,]+\s+(?:view|comment|like|share|follower|subscriber|"
    r"online|visitor|download|member|repl|reaction|vote|watch|"
    r"reader|user|people|impression|click|post|upvote|point)s?\b",
    re.IGNORECASE,
)
RE_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
RE_HEX_TOKEN = re.compile(r"\b[0-9a-fA-F]{16,}\b")
RE_BASE64_TOKEN = re.compile(r"\b[A-Za-z0-9+/]{16,}={0,3}\b")

# specific patterns must replace before generic hex
NOISE_PATTERNS = [
    (RE_UUID,          "[UUID]"),
    (RE_NAMED_DATE,    "[DATE]"),
    (RE_ISO_DATE,      "[DATE]"),
    (RE_DMY_DATE,      "[DATE]"),
    (RE_TIME,          "[TIME]"),
    (RE_RELATIVE_TIME, "[RELATIVE_TIME]"),
    (RE_UPDATED,       "[UPDATED]"),
    (RE_COUNTER,       "[COUNTER]"),
    (RE_HEX_TOKEN,     "[TOKEN]"),
    (RE_BASE64_TOKEN,  "[TOKEN]"),
]

AD_SELECTORS = [
    '[id*="ad-"]',
    '[id*="ad_"]',
    '[class*="advert"]',
    '[class*="banner"]',
    '[class*="cookie"]',
    '[class*="consent"]',
    '.ads',
    'ins.adsbygoogle',
    '[id*="sponsor"]',
    '[class*="sponsor"]',
    '[class*="promo"]',
    '[class*="popup"]',
    '[class*="modal"]',
    '[class*="newsletter"]',
]

REMOVE_TAGS = ["script", "style", "noscript", "iframe", "svg"]


def parse_selector_lines(text):
    if not text:
        return []
    selectors = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line:
            selectors.append(line)
    return selectors


def extract_text_from_html(html, include_selectors="", ignore_selectors=""):
    bad_selectors = []
    soup = BeautifulSoup(html, "lxml")

    for tag_name in REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for selector in AD_SELECTORS:
        try:
            for element in soup.select(selector):
                element.decompose()
        except Exception:
            bad_selectors.append(selector)

    for selector in parse_selector_lines(ignore_selectors):
        try:
            for element in soup.select(selector):
                element.decompose()
        except Exception:
            bad_selectors.append(selector)

    include_list = parse_selector_lines(include_selectors)
    if include_list:
        text_parts = []
        for selector in include_list:
            try:
                for element in soup.select(selector):
                    t = element.get_text(separator="\n", strip=True)
                    if t:
                        text_parts.append(t)
            except Exception:
                bad_selectors.append(selector)
        extracted = "\n".join(text_parts)
    else:
        extracted = soup.get_text(separator="\n", strip=True)

    return extracted, bad_selectors


def normalize_text(raw_text):
    text = raw_text
    for pattern, placeholder in NOISE_PATTERNS:
        text = pattern.sub(placeholder, text)

    cleaned_lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compare_texts(old_text, new_text, sensitivity="medium"):
    old_lines = old_text.split("\n")
    new_lines = new_text.split("\n")

    differ = difflib.unified_diff(old_lines, new_lines, lineterm="")
    added_lines = []
    removed_lines = []

    for line in differ:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added_lines.append(line[1:])
        elif line.startswith("-"):
            removed_lines.append(line[1:])

    total_changed = len(added_lines) + len(removed_lines)
    total_lines = max(len(old_lines), len(new_lines), 1)
    changed_percent = (total_changed / total_lines) * 100

    if sensitivity == "high":
        threshold = SENSITIVITY_HIGH_PERCENT
    elif sensitivity == "low":
        threshold = SENSITIVITY_LOW_PERCENT
    else:
        threshold = SENSITIVITY_MEDIUM_PERCENT

    if sensitivity == "medium" and total_lines < SHORT_TEXT_LINE_THRESHOLD:
        is_meaningful = total_changed >= 1
    else:
        if sensitivity == "high":
            is_meaningful = total_changed > 0
        else:
            is_meaningful = changed_percent >= threshold

    return {
        "is_meaningful": is_meaningful,
        "changed_line_percent": round(changed_percent, 2),
        "added_lines": added_lines,
        "removed_lines": removed_lines,
    }
