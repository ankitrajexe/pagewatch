# scripts/try_fetch.py
# --------------------
# What it does: A small test script to try out the fetcher manually.
#               Give it a URL on the command line and it will fetch the page,
#               print some info, and save a screenshot.
# Talks to: pagewatch/fetcher.py (BrowserSession)
#
# Usage:
#   python scripts/try_fetch.py http://127.0.0.1:5001/
#   python scripts/try_fetch.py https://example.com

import sys
import os

# Make sure Python can find the pagewatch package
# (we might be running from the project root)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pagewatch.fetcher import BrowserSession


def main():
    """Fetch a URL given on the command line and show the results."""

    # Check that the user gave us a URL
    if len(sys.argv) < 2:
        print("Usage: python scripts/try_fetch.py <URL>")
        print("Example: python scripts/try_fetch.py http://127.0.0.1:5001/")
        sys.exit(1)

    url = sys.argv[1]
    print(f"Fetching: {url}")
    print("-" * 60)

    # Create the browser, fetch the page, then close the browser
    session = BrowserSession()
    session.start()

    result = session.fetch_page(url, timeout_seconds=30)

    session.stop()

    # Print the results
    print(f"OK:          {result['ok']}")
    print(f"HTTP status: {result['http_status']}")
    print(f"Final URL:   {result['final_url']}")
    print(f"Duration:    {result['duration_ms']} ms")

    if result["error_type"] is not None:
        print(f"Error type:  {result['error_type']}")
        print(f"Error msg:   {result['error_message']}")

    # Show the first 300 characters of visible text
    text_preview = result["page_text"][:300]
    print(f"\nPage text (first 300 chars):")
    print("-" * 60)
    print(text_preview)
    print("-" * 60)

    # Save the screenshot
    screenshot_path = os.path.join("data", "try_fetch.png")
    os.makedirs("data", exist_ok=True)

    if result["screenshot_bytes"]:
        with open(screenshot_path, "wb") as f:
            f.write(result["screenshot_bytes"])
        print(f"\nScreenshot saved to: {screenshot_path}")
    else:
        print("\nNo screenshot (page failed to load).")

    print("Done!")


if __name__ == "__main__":
    main()
