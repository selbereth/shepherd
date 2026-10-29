import sqlite3
import time
from contextlib import contextmanager

from .blocklist import BLOCKLIST_VERSION, DOMAINS
from .config import BUILTIN_BLOCKLIST, DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'browser',
    key TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    last_seen REAL
);
CREATE TABLE IF NOT EXISTS banned_domains (
    domain TEXT PRIMARY KEY,
    reason TEXT,
    added_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    ts REAL NOT NULL,
    url TEXT NOT NULL,
    domain TEXT NOT NULL,
    title TEXT,
    score INTEGER NOT NULL,
    verdict TEXT NOT NULL,
    reasons TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS events_verdict ON events(verdict);
"""


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript(SCHEMA)
        cols = {r["name"] for r in db.execute("PRAGMA table_info(devices)")}
        if "last_seen" not in cols:
            db.execute("ALTER TABLE devices ADD COLUMN last_seen REAL")
        _seed_blocklist(db)


def _seed_blocklist(db) -> None:
    if not BUILTIN_BLOCKLIST:
        return
    row = db.execute("SELECT value FROM meta WHERE key = 'blocklist_version'").fetchone()
    if row and int(row["value"]) >= BLOCKLIST_VERSION:
        return
    db.executemany(
        "INSERT OR IGNORE INTO banned_domains VALUES (?, 'builtin list', ?)",
        [(d, now()) for d in DOMAINS],
    )
    db.execute("INSERT OR REPLACE INTO meta VALUES ('blocklist_version', ?)", (str(BLOCKLIST_VERSION),))


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()


def now() -> float:
    return time.time()
