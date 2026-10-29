"""Pulls published domain lists into SQLite and keeps them fresh.

Two lists, both hosts-format or one-domain-per-line URLs:
  adult  hard-blocked by the server (StevenBlack/hosts porn-only by default)
  ads    ads/trackers/malware, blocked in the browser with a "proceed anyway" page
"""
import logging
import urllib.request
from dataclasses import dataclass

from . import config
from .db import connect, now

log = logging.getLogger("shepherd")
MAX_BYTES = 60 * 1024 * 1024
SKIP = {"localhost", "localhost.localdomain", "local", "broadcasthost", "ip6-localhost", "ip6-loopback", "0.0.0.0"}


@dataclass(frozen=True)
class Feed:
    kind: str
    table: str  # fixed names from FEEDS below, never user input
    meta: str

    @property
    def url(self) -> str:
        return config.FEED_URL if self.kind == "adult" else config.ADS_FEED_URL


FEEDS = {
    "adult": Feed("adult", "feed_domains", "feed"),
    "ads": Feed("ads", "ads_domains", "ads"),
}


def parse(text: str) -> set[str]:
    """Accept hosts-format ('0.0.0.0 example.com') or bare-domain lines; ignore comments."""
    out = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if not line:
            continue
        parts = line.split()
        dom = parts[-1] if len(parts) <= 2 else ""
        dom = dom.removeprefix("*.").removeprefix("www.")
        if dom and "." in dom and dom not in SKIP and "/" not in dom and ":" not in dom:
            out.add(dom)
    return out


def _download(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "shepherd"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("feed too large")
    return data.decode("utf-8", "ignore")


def bump_rev(db) -> None:
    """Change the ad-block version so extensions re-download (list refreshed or allowlist edited)."""
    db.execute("INSERT OR REPLACE INTO meta VALUES ('adblock_rev', ?)", (str(now()),))


def refresh(kind: str = "adult") -> int:
    """Download and swap in a feed. A failed or empty download leaves the old list untouched."""
    feed = FEEDS[kind]
    domains = parse(_download(feed.url))
    if len(domains) < 100:
        raise ValueError(f"feed looks wrong: only {len(domains)} domains parsed")
    with connect() as db:
        db.execute(f"DELETE FROM {feed.table}")
        db.executemany(f"INSERT INTO {feed.table} VALUES (?)", ((d,) for d in sorted(domains)))
        db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"{feed.meta}_updated", str(now())))
        db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"{feed.meta}_count", str(len(domains))))
        db.execute("DELETE FROM meta WHERE key = ?", (f"{feed.meta}_error",))
        if kind == "ads":
            bump_rev(db)
    log.info("%s feed updated: %d domains", kind, len(domains))
    return len(domains)


def status(kind: str = "adult") -> dict:
    feed = FEEDS[kind]
    with connect() as db:
        m = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM meta WHERE key LIKE ?", (feed.meta + "_%",))}
    return {
        "enabled": bool(feed.url),
        "url": feed.url,
        "count": int(m.get(f"{feed.meta}_count", 0)),
        "updated": float(m[f"{feed.meta}_updated"]) if f"{feed.meta}_updated" in m else None,
        "error": m.get(f"{feed.meta}_error"),
        "every_days": config.FEED_DAYS,
    }


def is_stale(kind: str = "adult") -> bool:
    if not FEEDS[kind].url:
        return False
    updated = status(kind)["updated"]
    return updated is None or now() - updated > config.FEED_DAYS * 86400


def record_error(msg: str, kind: str = "adult") -> None:
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"{FEEDS[kind].meta}_error", msg[:300]))
