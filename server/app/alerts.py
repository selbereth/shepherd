"""Outbound notifications: ntfy, generic webhook, SMTP email. Stdlib only."""
import json
import logging
import smtplib
import threading
import time
import urllib.request
from email.message import EmailMessage

from . import config
from .db import connect, now

log = logging.getLogger("shepherd.alerts")

_lock = threading.Lock()
_last_sent: dict[tuple, float] = {}
_offline: set[str] = set()


def configured() -> list[str]:
    out = []
    if config.NTFY_URL:
        out.append("ntfy")
    if config.WEBHOOK_URL:
        out.append("webhook")
    if config.SMTP_HOST and config.EMAIL_TO:
        out.append("email")
    return out


def _http_post(url: str, data: bytes, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=10).read()


def _ntfy(title: str, body: str, priority: str) -> None:
    headers = {
        "Title": title.encode("ascii", "replace").decode(),
        "Priority": priority,
        "Tags": "shepherd",
    }
    if config.NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {config.NTFY_TOKEN}"
    _http_post(config.NTFY_URL, body.encode(), headers)


def _webhook(title: str, body: str, priority: str) -> None:
    text = f"{title}\n{body}"
    payload = {"title": title, "body": body, "priority": priority, "text": text, "content": text}
    _http_post(config.WEBHOOK_URL, json.dumps(payload).encode(), {"Content-Type": "application/json"})


def _email(title: str, body: str, priority: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = config.SMTP_FROM or config.SMTP_USER
    msg["To"] = config.EMAIL_TO
    msg.set_content(body)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
        s.starttls()
        if config.SMTP_USER:
            s.login(config.SMTP_USER, config.SMTP_PASS)
        s.send_message(msg)


def send(title: str, body: str, priority: str = "default") -> None:
    """Send to every configured channel; one failing channel doesn't stop the others."""
    for name, fn, on in (
        ("ntfy", _ntfy, config.NTFY_URL),
        ("webhook", _webhook, config.WEBHOOK_URL),
        ("email", _email, config.SMTP_HOST and config.EMAIL_TO),
    ):
        if not on:
            continue
        try:
            fn(title, body, priority)
        except Exception:
            log.exception("alert via %s failed", name)


def should_alert(verdict: str) -> bool:
    return verdict == "block" or (verdict == "warn" and config.ALERT_ON == "warn")


def notify_event(device_name: str, url: str, domain: str, verdict: str, score: int, reasons: list[str]) -> None:
    key = (device_name, domain, verdict)
    with _lock:
        t = time.monotonic()
        if t - _last_sent.get(key, -1e12) < config.ALERT_COOLDOWN:
            return
        _last_sent[key] = t
    label = "Blocked" if verdict == "block" else "Suspicious"
    send(
        f"{label}: {domain} on {device_name}",
        f"{url}\nScore {score}. {'; '.join(reasons) or 'no details'}",
        priority="high" if verdict == "block" else "default",
    )


def check_offline() -> None:
    """Alert once when a device stops checking in, and once when it returns."""
    if config.OFFLINE_MINUTES <= 0:
        return
    cutoff = now() - config.OFFLINE_MINUTES * 60
    with connect() as db:
        rows = db.execute("SELECT id, name, last_seen FROM devices WHERE last_seen IS NOT NULL").fetchall()
    for r in rows:
        stale = r["last_seen"] < cutoff
        if stale and r["id"] not in _offline:
            _offline.add(r["id"])
            send(
                f"{r['name']} stopped checking in",
                f"No contact for over {config.OFFLINE_MINUTES} minutes. The device may be off, "
                "offline, or the extension was disabled or removed.",
                priority="high",
            )
        elif not stale and r["id"] in _offline:
            _offline.discard(r["id"])
            send(f"{r['name']} is back online", "The device is checking in again.")
