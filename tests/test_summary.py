# test_summary.py
# ---------------
# Unit tests for rule-based change summary generation (pagewatch/summary.py):
# - Price/number changes with percent difference
# - Stock status phrase flips ('Out of stock' / 'In stock')
# - Keyword appearing or disappearing
# - New section appearing
# - Fallback line change counts and trimming

import pytest
from pagewatch.summary import make_summary


def test_make_summary_price_drop_with_percent():
    old = "Special Offer: Price is $499 today!"
    new = "Special Offer: Price is $459 today!"
    summary = make_summary(old, new)
    assert summary == "Price dropped from 499 to 459 (-8.0%)"


def test_make_summary_price_rise_with_percent():
    old = "Item price: € 100 per unit"
    new = "Item price: € 125 per unit"
    summary = make_summary(old, new)
    assert summary == "Price rose from 100 to 125 (+25.0%)"


def test_make_summary_single_number_decimal_change():
    old = "Balance: 1250.50 USD\nStatus: Active"
    new = "Balance: 1100.25 USD\nStatus: Active"
    summary = make_summary(old, new)
    assert summary == "Price dropped from 1250.50 to 1100.25 (-12.0%)"


def test_make_summary_number_change_non_price():
    # Number decreased without currency context
    old = "Remaining slots: 50 available"
    new = "Remaining slots: 40 available"
    assert make_summary(old, new) == "Number dropped from 50 to 40 (-20.0%)"

    # Number increased
    old = "Points scored: 100"
    new = "Points scored: 150"
    assert make_summary(old, new) == "Number rose from 100 to 150 (+50.0%)"


def test_make_summary_stock_flip_out_to_in():
    old = "Product: Mechanical Keyboard\nAvailability: Out of stock"
    new = "Product: Mechanical Keyboard\nAvailability: In stock"
    assert make_summary(old, new) == "Changed from 'Out of stock' to 'In stock'"

    # Also handles 'Sold out' -> 'In stock'
    old_sold = "Product: Headphones\nStatus: Sold out"
    new_avail = "Product: Headphones\nStatus: Back in stock"
    assert make_summary(old_sold, new_avail) == "Changed from 'Out of stock' to 'In stock'"


def test_make_summary_stock_flip_in_to_out():
    old = "Product: Monitor\nAvailability: In stock"
    new = "Product: Monitor\nAvailability: Out of stock"
    assert make_summary(old, new) == "Changed from 'In stock' to 'Out of stock'"


def test_make_summary_keyword_appearance():
    # Keyword appeared
    old = "Welcome to our store. Browse our regular catalog."
    new = "Welcome to our store. Huge Black Friday Sale now live!"
    summary = make_summary(old, new, keyword="Sale")
    assert summary == "Keyword 'Sale' appeared"

    # Keyword disappeared
    old = "Flash discount expires in 1 hour."
    new = "All standard items listed below."
    summary = make_summary(old, new, keyword="discount")
    assert summary == "Keyword 'discount' disappeared"

    # Keyword presence unchanged -> falls through to other rules
    old = "Discount: 10%"
    new = "Discount: 20%"
    summary = make_summary(old, new, keyword="Discount")
    assert "Number rose from 10 to 20 (+100.0%)" in summary or "Price" in summary


def test_make_summary_new_section_appeared():
    # Markdown heading
    old = "Product Details\nReliable device."
    new = "Product Details\nReliable device.\n\n## Customer Reviews\nFive stars!"
    summary = make_summary(old, new)
    assert summary == "New section appeared: 'Customer Reviews'"

    # Colon heading
    old = "Intro text"
    new = "Intro text\n\nSpecifications:\nWeight: 100g\nDimensions: 5x5"
    summary = make_summary(old, new)
    assert summary == "New section appeared: 'Specifications'"

    # Bracketed heading
    old = "Page 1"
    new = "Page 1\n\n[Release Notes]\nVersion 2.0 launched"
    summary = make_summary(old, new)
    assert summary == "New section appeared: 'Release Notes'"


def test_make_summary_lines_added_and_removed():
    old = "Alpha\nBeta\nGamma"
    new = "Alpha\nBeta Modified\nDelta\nEpsilon"
    summary = make_summary(old, new)
    assert "3 lines added, 2 removed" in summary
    assert '+ "' in summary
    assert '- "' in summary


def test_make_summary_only_lines_added():
    old = "Feature 1\nFeature 2"
    new = "Feature 1\nFeature 2\nFeature 3"
    summary = make_summary(old, new)
    assert summary.startswith("1 line added, 0 removed")
    assert '+ "Feature 3"' in summary


def test_make_summary_only_lines_removed():
    old = "Header\nDeprecated section\nFooter"
    new = "Header\nFooter"
    summary = make_summary(old, new)
    assert summary.startswith("0 lines added, 1 removed")
    assert '- "Deprecated section"' in summary


def test_make_summary_long_line_trimmed():
    old = "Start"
    new = "Start\n" + "A" * 120
    summary = make_summary(old, new)
    assert summary.startswith("1 line added, 0 removed")
    assert "..." in summary
    # Check that the example text length does not exceed 80 + formatting
    example = summary.split('+ "')[1].split('"')[0]
    assert len(example) <= 80


def test_make_summary_identical_text():
    text = "Line 1\nLine 2"
    assert make_summary(text, text) == "0 lines added, 0 removed"


def test_make_summary_empty_or_none():
    assert make_summary("", "") == "0 lines added, 0 removed"
    assert make_summary(None, None) == "0 lines added, 0 removed"
    summary = make_summary(None, "Hello World")
    assert summary.startswith("1 line added, 0 removed")
