import os
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = os.environ.get("DATA_DIR", "data")
DB_PATH = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "pagewatch.db"))
SCREENSHOT_DIR = os.path.join(DATA_DIR, "screenshots")
TEXT_DIR = os.path.join(DATA_DIR, "texts")
DIFF_DIR = os.path.join(DATA_DIR, "diffs")
PICKER_DIR = os.path.join(DATA_DIR, "picker")

# fast mode allows 1-2 min checks and lower delays for demos
DEV_FAST_MODE = os.environ.get("DEV_FAST_MODE", "false").lower() in ("true", "1", "yes")

MIN_INTERVAL_MINUTES = 1 if DEV_FAST_MODE else int(os.environ.get("MIN_INTERVAL_MINUTES", "15"))
MAX_INTERVAL_MINUTES = int(os.environ.get("MAX_INTERVAL_MINUTES", "1440"))
PAGE_TIMEOUT_SECONDS = int(os.environ.get("PAGE_TIMEOUT_SECONDS", "45"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
DOMAIN_DELAY_SECONDS = 2 if DEV_FAST_MODE else int(os.environ.get("DOMAIN_DELAY_SECONDS", "10"))
ALLOW_LOCALHOST = os.environ.get("ALLOW_LOCALHOST", "true").lower() in ("true", "1", "yes")
ROBOTS_SKIP_LOCALHOST = os.environ.get("ROBOTS_SKIP_LOCALHOST", "true").lower() in ("true", "1", "yes")

SENSITIVITY_HIGH_PERCENT = 0.0
SENSITIVITY_MEDIUM_PERCENT = 2.0
SENSITIVITY_LOW_PERCENT = 10.0
SHORT_TEXT_LINE_THRESHOLD = 50
NOISY_STREAK_LIMIT = 5

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5000")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(TEXT_DIR, exist_ok=True)
os.makedirs(DIFF_DIR, exist_ok=True)
os.makedirs(PICKER_DIR, exist_ok=True)
