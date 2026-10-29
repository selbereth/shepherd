import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import alerts, config
from .db import connect, init_db, now
from .scoring import score_page, verdict_for

log = logging.getLogger("shepherd")
STATIC = Path(__file__).parent / "static"


async def _watch_devices() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await asyncio.to_thread(alerts.check_offline)
        except Exception:
            log.exception("offline check failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not config.ADMIN_KEY:
        raise RuntimeError("Set SHEPHERD_ADMIN_KEY before starting the server")
    init_db()
    task = asyncio.create_task(_watch_devices())
    yield
    task.cancel()


app = FastAPI(title="Shepherd", lifespan=lifespan)


def admin(x_admin_key: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_admin_key, config.ADMIN_KEY):
        raise HTTPException(401, "bad admin key")


def device(x_device_key: str = Header(default="")) -> dict:
    """Authenticate a client and record that it checked in."""
    with connect() as db:
        row = db.execute("SELECT id, name FROM devices WHERE key = ?", (x_device_key,)).fetchone()
        if not row:
            raise HTTPException(401, "unknown device")
        db.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (now(), row["id"]))
    return dict(row)


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def is_banned(db, domain: str) -> bool:
    parts = domain.split(".")
    candidates = [".".join(parts[i:]) for i in range(len(parts) - 1)] or [domain]
    q = ",".join("?" * len(candidates))
    return db.execute(f"SELECT 1 FROM banned_domains WHERE domain IN ({q})", candidates).fetchone() is not None


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC / "index.html")


# ---- client API (extension / android app) ----

class PageReport(BaseModel):
    url: str
    title: str = ""
    text: str = Field(default="", max_length=config.MAX_TEXT_CHARS)


@app.post("/api/check")
def check(report: PageReport, background: BackgroundTasks, dev: dict = Depends(device)) -> dict:
    domain = domain_of(report.url)
    with connect() as db:
        if is_banned(db, domain):
            score, reasons, verdict = 100, ["banned domain"], "block"
        else:
            res = score_page(report.url, report.title, report.text)
            score, reasons = res.score, res.reasons
            verdict = verdict_for(score, config.WARN_SCORE, config.BLOCK_SCORE)
            if verdict == "block" and config.AUTO_BAN and domain:
                db.execute(
                    "INSERT OR IGNORE INTO banned_domains VALUES (?, ?, ?)",
                    (domain, "auto: " + "; ".join(reasons), now()),
                )
        db.execute(
            "INSERT INTO events (device_id, ts, url, domain, title, score, verdict, reasons)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (dev["id"], now(), report.url, domain, report.title, score, verdict, "; ".join(reasons)),
        )
    if verdict != "allow" and alerts.should_alert(verdict):
        background.add_task(alerts.notify_event, dev["name"], report.url, domain, verdict, score, reasons)
    return {"verdict": verdict, "score": score, "reasons": reasons}


@app.get("/api/banned")
def banned(_: dict = Depends(device)) -> dict:
    with connect() as db:
        rows = db.execute("SELECT domain FROM banned_domains ORDER BY domain").fetchall()
    return {"domains": [r["domain"] for r in rows]}


# ---- admin API ----

class NewDevice(BaseModel):
    name: str
    kind: str = "browser"


@app.post("/admin/devices", dependencies=[Depends(admin)])
def add_device(body: NewDevice) -> dict:
    dev_id, key = secrets.token_hex(4), secrets.token_urlsafe(32)
    with connect() as db:
        db.execute(
            "INSERT INTO devices (id, name, kind, key, created_at) VALUES (?,?,?,?,?)",
            (dev_id, body.name, body.kind, key, now()),
        )
    return {"id": dev_id, "key": key}


@app.get("/admin/devices", dependencies=[Depends(admin)])
def list_devices() -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT id, name, kind, created_at, last_seen FROM devices ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/admin/devices/{dev_id}", dependencies=[Depends(admin)])
def delete_device(dev_id: str) -> dict:
    with connect() as db:
        db.execute("DELETE FROM devices WHERE id = ?", (dev_id,))
    alerts._offline.discard(dev_id)
    return {"ok": True}


class Ban(BaseModel):
    domain: str
    reason: str = "manual"


@app.get("/admin/banned", dependencies=[Depends(admin)])
def list_banned() -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT domain, reason, added_at FROM banned_domains ORDER BY domain").fetchall()
    return [dict(r) for r in rows]


@app.post("/admin/banned", dependencies=[Depends(admin)])
def ban(body: Ban) -> dict:
    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO banned_domains VALUES (?,?,?)",
            (body.domain.lower().removeprefix("www."), body.reason, now()),
        )
    return {"ok": True}


@app.delete("/admin/banned/{domain}", dependencies=[Depends(admin)])
def unban(domain: str) -> dict:
    with connect() as db:
        db.execute("DELETE FROM banned_domains WHERE domain = ?", (domain.lower(),))
    return {"ok": True}


@app.get("/admin/events", dependencies=[Depends(admin)])
def events(limit: int = 100, verdict: str | None = None) -> list[dict]:
    sql = "SELECT e.*, d.name AS device_name FROM events e LEFT JOIN devices d ON d.id = e.device_id"
    args: list = []
    if verdict:
        sql += " WHERE e.verdict = ?"
        args.append(verdict)
    sql += " ORDER BY e.ts DESC LIMIT ?"
    args.append(min(limit, 1000))
    with connect() as db:
        return [dict(r) for r in db.execute(sql, args).fetchall()]


@app.get("/admin/stats", dependencies=[Depends(admin)])
def stats() -> dict:
    since = now() - 86400
    with connect() as db:
        by_verdict = {
            r["verdict"]: r["n"]
            for r in db.execute(
                "SELECT verdict, COUNT(*) n FROM events WHERE ts > ? GROUP BY verdict", (since,)
            )
        }
        top = [
            dict(r)
            for r in db.execute(
                "SELECT domain, COUNT(*) n FROM events WHERE ts > ? AND verdict != 'allow' GROUP BY domain ORDER BY n DESC LIMIT 5",
                (since,),
            )
        ]
    return {
        "last_24h": {
            "allow": by_verdict.get("allow", 0),
            "warn": by_verdict.get("warn", 0),
            "block": by_verdict.get("block", 0),
        },
        "top_domains": top,
        "alert_channels": alerts.configured(),
        "offline_minutes": config.OFFLINE_MINUTES,
    }


@app.post("/admin/alerts/test", dependencies=[Depends(admin)])
def test_alert() -> dict:
    channels = alerts.configured()
    if not channels:
        raise HTTPException(400, "no alert channel configured")
    alerts.send("Shepherd test alert", "If you can read this, alerts are working.")
    return {"sent_to": channels}
