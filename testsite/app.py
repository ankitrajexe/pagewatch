# testsite/app.py
# ---------------
# What it does: A tiny Flask website that I control, for testing PageWatch.
#               It has pages with noise (timestamps, counters, banners, tokens)
#               and special pages to simulate errors, CAPTCHAs, and slowness.
# Talks to: nothing. This is a standalone test server on port 5001.

import time
import random
import string
from datetime import datetime
from flask import Flask

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory state (resets when the server restarts)
# ---------------------------------------------------------------------------

# The product price, changeable via /set-price/<n>
current_price = 499

# The stable paragraph text, changeable via /set-text/<words>
current_text = "This is a great product. It has been trusted by thousands of customers worldwide. Quality guaranteed."

# View counter, goes up by 1 on every page load
view_count = 1234

# List of banners that rotate randomly on each load
BANNERS = [
    "Summer Sale - 20% off everything!",
    "Free shipping on orders over $50!",
    "New arrivals just landed!",
    "Limited time offer - buy one get one free!",
    "Welcome to our store!",
]


def make_random_token(length=32):
    """Generate a random hex string, like a session token or tracking ID."""
    return "".join(random.choices(string.hexdigits.lower(), k=length))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def product_page():
    """
    The main product page. Has lots of 'noise' that changes on every load:
    - A live timestamp
    - A rotating banner (random pick from the list)
    - A random token hidden in the page
    - A view counter that goes up each load
    And some 'stable' content:
    - The product name
    - The current price (only changes when I visit /set-price/<n>)
    - The paragraph text (only changes when I visit /set-text/<words>)
    """
    global view_count
    view_count = view_count + 1

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    banner = random.choice(BANNERS)
    token = make_random_token()

    html = f"""<!DOCTYPE html>
<html>
<head><title>Test Store</title></head>
<body>
    <div class="banner">{banner}</div>

    <h1>Super Widget Pro</h1>
    <p class="price">Price: ${current_price}</p>

    <p class="description">{current_text}</p>

    <p class="timestamp">Last updated: {now}</p>
    <p class="views">{view_count:,} views</p>

    <span class="token" style="font-size:1px; color:#fff;">{token}</span>

    <p>2 minutes ago - someone purchased this item</p>
</body>
</html>"""
    return html


@app.route("/set-price/<int:price>")
def set_price(price):
    """Change the product price. Visit /set-price/999 to set price to 999."""
    global current_price
    current_price = price
    return f"Price set to ${price}. <a href='/'>Go back</a>"


@app.route("/set-text/<path:words>")
def set_text(words):
    """Change the stable paragraph text. Visit /set-text/hello world to update."""
    global current_text
    current_text = words
    return f"Text set to: {words}. <a href='/'>Go back</a>"


@app.route("/captcha")
def captcha_page():
    """Simulates a CAPTCHA / bot-detection page."""
    return """<!DOCTYPE html>
<html>
<head><title>Verify</title></head>
<body>
    <h1>Please verify you are human</h1>
    <p>Complete the captcha below to continue.</p>
    <div class="captcha-box">[CAPTCHA WIDGET PLACEHOLDER]</div>
</body>
</html>"""


@app.route("/down")
def down_page():
    """Simulates a server error (HTTP 500)."""
    return "Internal Server Error", 500


@app.route("/slow")
def slow_page():
    """Simulates a very slow page (sleeps 60 seconds). Good for testing timeouts."""
    time.sleep(60)
    return "Finally loaded (after 60 seconds)."


@app.route("/always-different")
def always_different():
    """Returns completely different content on every single load."""
    random_words = " ".join(
        "".join(random.choices(string.ascii_lowercase, k=random.randint(3, 10)))
        for _ in range(50)
    )
    random_number = random.randint(1, 1000000)
    token = make_random_token(64)

    return f"""<!DOCTYPE html>
<html>
<head><title>Always Different</title></head>
<body>
    <h1>Page #{random_number}</h1>
    <p>{random_words}</p>
    <p>Token: {token}</p>
    <p>Time: {time.time()}</p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Run the test site
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Test site starting on http://127.0.0.1:5001")
    print("Routes: / /set-price/<n> /set-text/<words> /captcha /down /slow /always-different")
    app.run(host="127.0.0.1", port=5001, debug=True)
