import sqlite3
from pagewatch.config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS urls (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            url                  TEXT    NOT NULL UNIQUE,
            domain               TEXT    NOT NULL,
            last_fetched_at      TEXT,
            last_http_status     INTEGER,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            blocked_until        TEXT
        )
    """)

    try:
        cursor.execute("ALTER TABLE urls ADD COLUMN blocked_until TEXT")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monitors (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            name                 TEXT    NOT NULL,
            url_id               INTEGER NOT NULL REFERENCES urls(id),
            interval_minutes     INTEGER NOT NULL,
            sensitivity          TEXT    NOT NULL DEFAULT 'medium',
            include_selectors    TEXT    NOT NULL DEFAULT '',
            ignore_selectors     TEXT    NOT NULL DEFAULT '',
            keyword              TEXT    NOT NULL DEFAULT '',
            number_selector      TEXT    NOT NULL DEFAULT '',
            number_alert_below   REAL,
            number_alert_above   REAL,
            alert_email          TEXT    NOT NULL DEFAULT '',
            telegram_chat_id     TEXT    NOT NULL DEFAULT '',
            discord_webhook_url  TEXT    NOT NULL DEFAULT '',
            daily_digest         INTEGER NOT NULL DEFAULT 0,
            status               TEXT    NOT NULL DEFAULT 'pending',
            status_message       TEXT    NOT NULL DEFAULT '',
            last_checked_at      TEXT,
            last_changed_at      TEXT,
            next_check_at        TEXT,
            noisy_streak         INTEGER NOT NULL DEFAULT 0,
            is_noisy             INTEGER NOT NULL DEFAULT 0,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            is_active            INTEGER NOT NULL DEFAULT 1,
            created_at           TEXT    NOT NULL
        )
    """)

    try:
        cursor.execute("ALTER TABLE monitors ADD COLUMN number_alert_below REAL")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE monitors ADD COLUMN number_alert_above REAL")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id      INTEGER NOT NULL REFERENCES monitors(id),
            taken_at        TEXT    NOT NULL,
            content_hash    TEXT    NOT NULL,
            text_path       TEXT    NOT NULL,
            screenshot_path TEXT    NOT NULL,
            text_length     INTEGER NOT NULL DEFAULT 0,
            summary         TEXT    NOT NULL DEFAULT ''
        )
    """)

    try:
        cursor.execute("ALTER TABLE snapshots ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url_id      INTEGER NOT NULL REFERENCES urls(id),
            monitor_id  INTEGER REFERENCES monitors(id),
            job_type    TEXT    NOT NULL DEFAULT 'check',
            status      TEXT    NOT NULL DEFAULT 'queued',
            attempts    INTEGER NOT NULL DEFAULT 0,
            run_after   TEXT,
            created_at  TEXT    NOT NULL,
            started_at  TEXT,
            finished_at TEXT,
            error       TEXT
        )
    """)

    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN monitor_id INTEGER REFERENCES monitors(id)")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'check'")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS check_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id  INTEGER NOT NULL REFERENCES monitors(id),
            checked_at  TEXT    NOT NULL,
            outcome     TEXT    NOT NULL,
            message     TEXT    NOT NULL DEFAULT '',
            http_status INTEGER,
            duration_ms INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id  INTEGER NOT NULL REFERENCES monitors(id),
            snapshot_id INTEGER REFERENCES snapshots(id),
            channel     TEXT    NOT NULL,
            dedupe_key  TEXT    NOT NULL UNIQUE,
            summary     TEXT    NOT NULL DEFAULT '',
            sent_at     TEXT    NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS number_points (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id  INTEGER NOT NULL REFERENCES monitors(id),
            snapshot_id INTEGER REFERENCES snapshots(id),
            value       REAL    NOT NULL,
            taken_at    TEXT    NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def run_query(sql, params=None):
    if params is None:
        params = ()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    return rows


def run_write(sql, params=None):
    if params is None:
        params = ()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id
