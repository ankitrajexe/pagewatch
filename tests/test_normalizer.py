# tests/test_normalizer.py
# -------------------------
# What it does: Tests for the normalizer module — noise removal, hashing,
#               sensitivity comparison, and HTML extraction with selectors.
# Talks to: pagewatch/normalizer.py

import pytest
from pagewatch.normalizer import (
    normalize_text,
    hash_text,
    compare_texts,
    extract_text_from_html,
    parse_selector_lines,
)


# ============================================================================
# Tests for normalize_text — noise removal
# ============================================================================

class TestNormalizeTimestamps:
    """Tests that timestamps and dates are replaced with placeholders."""

    def test_iso_date_removed(self):
        """ISO date like '2026-10-16' should become '[DATE]'."""
        text = "Published on 2026-10-16 by admin"
        result = normalize_text(text)
        assert "2026-10-16" not in result
        assert "[DATE]" in result
        assert "admin" in result  # other text stays

    def test_named_date_removed(self):
        """Named date like 'Oct 16, 2026' should become '[DATE]'."""
        text = "Updated on Oct 16, 2026"
        result = normalize_text(text)
        assert "Oct 16, 2026" not in result
        assert "[DATE]" in result

    def test_dmy_date_removed(self):
        """Day/month/year date like '16/10/2026' should become '[DATE]'."""
        text = "Date: 16/10/2026"
        result = normalize_text(text)
        assert "16/10/2026" not in result
        assert "[DATE]" in result

    def test_time_removed(self):
        """Time like '12:45:10' should become '[TIME]'."""
        text = "Last seen at 12:45:10 today"
        result = normalize_text(text)
        assert "12:45:10" not in result
        assert "[TIME]" in result

    def test_relative_time_removed(self):
        """'5 minutes ago' should become '[RELATIVE_TIME]'."""
        text = "Posted 5 minutes ago by user"
        result = normalize_text(text)
        assert "5 minutes ago" not in result
        assert "[RELATIVE_TIME]" in result


class TestNormalizeCountersAndTokens:
    """Tests that counters, UUIDs, and tokens are replaced."""

    def test_counter_removed(self):
        """'1,234 views' should become '[COUNTER]'."""
        text = "This page has 1,234 views"
        result = normalize_text(text)
        assert "1,234 views" not in result
        assert "[COUNTER]" in result

    def test_uuid_removed(self):
        """A UUID should become '[UUID]'."""
        text = "Session: 550e8400-e29b-41d4-a716-446655440000"
        result = normalize_text(text)
        assert "550e8400-e29b-41d4-a716-446655440000" not in result
        assert "[UUID]" in result

    def test_hex_token_removed(self):
        """A long hex string (16+ chars) should become '[TOKEN]'."""
        text = "Token: dc6ba33d2db0ea24d9dbed10aeb14f6e"
        result = normalize_text(text)
        assert "dc6ba33d2db0ea24d9dbed10aeb14f6e" not in result
        assert "[TOKEN]" in result

    def test_empty_lines_dropped(self):
        """Empty lines and extra whitespace should be cleaned up."""
        text = "Hello\n\n\n   \n  World  \n\n"
        result = normalize_text(text)
        assert result == "Hello\nWorld"


# ============================================================================
# Tests for hash_text — hashing
# ============================================================================

class TestHashText:
    """Tests for SHA-256 hashing."""

    def test_same_text_same_hash(self):
        """Two identical texts must produce the same hash."""
        text = "Hello World"
        assert hash_text(text) == hash_text(text)

    def test_different_text_different_hash(self):
        """Two different texts must produce different hashes."""
        assert hash_text("Hello") != hash_text("World")

    def test_timestamp_noise_same_hash(self):
        """
        Two texts that differ ONLY in a timestamp should give the same
        hash after normalization (this is the whole point of normalizing).
        """
        text_v1 = "Product price: $499\nLast updated: 2026-10-16 12:30:00\n1,234 views"
        text_v2 = "Product price: $499\nLast updated: 2026-10-17 09:15:22\n5,678 views"
        normalized_v1 = normalize_text(text_v1)
        normalized_v2 = normalize_text(text_v2)
        assert hash_text(normalized_v1) == hash_text(normalized_v2)

    def test_real_price_change_different_hash(self):
        """
        A real content change (price change) must still produce a
        different hash, even after normalization.
        """
        text_v1 = "Product price: $499\nLast updated: 2026-10-16 12:30:00"
        text_v2 = "Product price: $599\nLast updated: 2026-10-16 12:30:00"
        normalized_v1 = normalize_text(text_v1)
        normalized_v2 = normalize_text(text_v2)
        assert hash_text(normalized_v1) != hash_text(normalized_v2)


# ============================================================================
# Tests for compare_texts — sensitivity thresholds
# ============================================================================

class TestCompareTexts:
    """Tests for the sensitivity-aware text comparison."""

    def test_high_sensitivity_detects_one_word_change(self):
        """
        High sensitivity: even changing one word in a large text is meaningful.
        """
        old = "\n".join(["Line number " + str(i) for i in range(100)])
        new_lines = ["Line number " + str(i) for i in range(100)]
        new_lines[50] = "CHANGED LINE HERE"
        new = "\n".join(new_lines)

        result = compare_texts(old, new, sensitivity="high")
        assert result["is_meaningful"] is True
        assert len(result["added_lines"]) >= 1
        assert len(result["removed_lines"]) >= 1

    def test_medium_sensitivity_ignores_tiny_change_in_large_text(self):
        """
        Medium sensitivity on a 100-line text: changing 1 line = 1% change,
        which is below the 2% threshold, so NOT meaningful.
        (1 removed + 1 added = 2 changed, 2/100 = 2%, this is borderline)
        Let's use 200 lines and change 1 to be safely below 2%.
        """
        old = "\n".join(["Line number " + str(i) for i in range(200)])
        new_lines = ["Line number " + str(i) for i in range(200)]
        new_lines[100] = "CHANGED LINE"
        new = "\n".join(new_lines)

        result = compare_texts(old, new, sensitivity="medium")
        # 2 changed out of 200 = 1%, below 2% threshold
        assert result["is_meaningful"] is False

    def test_medium_sensitivity_short_text_one_line_change(self):
        """
        Medium sensitivity on a short text (under 50 lines):
        at least 1 changed line is enough to be meaningful.
        """
        old = "Line A\nLine B\nLine C"
        new = "Line A\nLine CHANGED\nLine C"

        result = compare_texts(old, new, sensitivity="medium")
        assert result["is_meaningful"] is True

    def test_low_sensitivity_ignores_small_change(self):
        """
        Low sensitivity: need at least 10% of lines changed.
        Changing 5 out of 100 lines = 5%, should NOT be meaningful.
        (5 removed + 5 added = 10, but 10/100 = 10%, borderline.
        Let's change 3 out of 100 to be safely below.)
        """
        old = "\n".join(["Line " + str(i) for i in range(100)])
        new_lines = ["Line " + str(i) for i in range(100)]
        new_lines[10] = "CHANGED A"
        new_lines[20] = "CHANGED B"
        new_lines[30] = "CHANGED C"
        new = "\n".join(new_lines)

        result = compare_texts(old, new, sensitivity="low")
        # 6 changed out of 100 = 6%, below 10% threshold
        assert result["is_meaningful"] is False

    def test_low_sensitivity_detects_large_change(self):
        """
        Low sensitivity: changing 15 out of 100 lines = 15%, above 10%.
        """
        old = "\n".join(["Line " + str(i) for i in range(100)])
        new_lines = ["Line " + str(i) for i in range(100)]
        for i in range(15):
            new_lines[i * 6] = "CHANGED " + str(i)
        new = "\n".join(new_lines)

        result = compare_texts(old, new, sensitivity="low")
        assert result["is_meaningful"] is True

    def test_identical_texts_not_meaningful(self):
        """Two identical texts should never be meaningful."""
        text = "Hello\nWorld\nFoo"
        result = compare_texts(text, text, sensitivity="high")
        assert result["is_meaningful"] is False
        assert result["changed_line_percent"] == 0.0
        assert result["added_lines"] == []
        assert result["removed_lines"] == []


# ============================================================================
# Tests for extract_text_from_html — selectors
# ============================================================================

SAMPLE_HTML = """
<html>
<head><script>var x = 1;</script><style>body{color:red;}</style></head>
<body>
    <div class="banner">Buy now! Sale!</div>
    <h1>Product Title</h1>
    <p class="price">Price: $499</p>
    <p class="description">Great product.</p>
    <div class="ads">Sponsored content here</div>
    <noscript>Enable JS</noscript>
    <footer>Copyright 2026</footer>
</body>
</html>
"""


class TestExtractTextFromHtml:
    """Tests for HTML text extraction with selectors."""

    def test_scripts_and_styles_removed(self):
        """Script and style tag content should not appear in the text."""
        text, bad = extract_text_from_html(SAMPLE_HTML)
        assert "var x = 1" not in text
        assert "body{color:red}" not in text
        assert bad == []

    def test_noscript_removed(self):
        """noscript content should not appear in the text."""
        text, bad = extract_text_from_html(SAMPLE_HTML)
        assert "Enable JS" not in text

    def test_ad_selector_removes_ads(self):
        """Elements matching the built-in .ads selector should be removed."""
        text, bad = extract_text_from_html(SAMPLE_HTML)
        assert "Sponsored content" not in text
        assert "Product Title" in text  # real content stays

    def test_ignore_selector_removes_region(self):
        """An ignore selector should remove that region from the text."""
        text, bad = extract_text_from_html(
            SAMPLE_HTML,
            ignore_selectors="footer"
        )
        assert "Copyright" not in text
        assert "Product Title" in text

    def test_include_selector_keeps_only_region(self):
        """Include selectors should keep ONLY text from those elements."""
        text, bad = extract_text_from_html(
            SAMPLE_HTML,
            include_selectors="p.price"
        )
        assert "Price: $499" in text
        assert "Product Title" not in text
        assert "Great product" not in text

    def test_include_selector_no_match_returns_empty(self):
        """If include selectors match nothing, return empty string."""
        text, bad = extract_text_from_html(
            SAMPLE_HTML,
            include_selectors=".nonexistent-class"
        )
        assert text == ""

    def test_bad_selector_does_not_crash(self):
        """An invalid CSS selector should be skipped and reported, not crash."""
        text, bad = extract_text_from_html(
            SAMPLE_HTML,
            ignore_selectors="[[[invalid selector"
        )
        # Should still extract text from the rest of the page
        assert "Product Title" in text
        # The bad selector should be reported
        assert "[[[invalid selector" in bad


class TestParseSelectorLines:
    """Tests for the selector line parser."""

    def test_basic_parsing(self):
        """Parses multi-line selectors correctly."""
        result = parse_selector_lines("div.price\n\nspan.title\n  ")
        assert result == ["div.price", "span.title"]

    def test_empty_string(self):
        """Empty string returns empty list."""
        assert parse_selector_lines("") == []

    def test_none_input(self):
        """None input returns empty list."""
        assert parse_selector_lines(None) == []
