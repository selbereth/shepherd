"""Pulls a published adult-site domain list and keeps it in the feed_domains table.

The default is StevenBlack/hosts' porn-only list (hosts format, ~77k domains). Any
hosts-format or one-domain-per-line URL works via SHEPHERD_FEED_URL.
"""
import logging
import urllib.request

from . import config
from .db import connect, now

log = logging.getLogger("shepherd")
MAX_BYTES = 60 * 1024 * 1024
SKIP = {"localhost", "localhost.localdomain", "local", "broadcasthost", "ip6-localhost", "ip6-loopback", "0.0.0.0"}


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


def refresh() -> int:
    """Download and swap in the feed. A failed or empty download leaves the old list untouched."""
    domains = parse(_download(config.FEED_URL))
    if len(domains) < 100:
        raise ValueError(f"feed looks wrong: only {len(domains)} domains parsed")
    with connect() as db:
        db.execute("DELETE FROM feed_domains")
        db.executemany("INSERT INTO feed_domains VALUES (?)", ((d,) for d in sorted(domains)))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('feed_updated', ?)", (str(now()),))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('feed_count', ?)", (str(len(domains)),))
        db.execute("DELETE FROM meta WHERE key = 'feed_error'")
    log.info("adult feed updated: %d domains", len(domains))
    return len(domains)


def status() -> dict:
    with connect() as db:
        m = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM meta WHERE key LIKE 'feed_%'")}
    return {
        "enabled": bool(config.FEED_URL),
        "url": config.FEED_URL,
        "count": int(m.get("feed_count", 0)),
        "updated": float(m["feed_updated"]) if "feed_updated" in m else None,
        "error": m.get("feed_error"),
        "every_days": config.FEED_DAYS,
    }


def is_stale() -> bool:
    if not config.FEED_URL:
        return False
    updated = status()["updated"]
    return updated is None or now() - updated > config.FEED_DAYS * 86400


def record_error(msg: str) -> None:
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO meta VALUES ('feed_error', ?)", (msg[:300],))
