import secrets
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import config
from .db import connect, init_db, now
from .scoring import score_page, verdict_for

app = FastAPI(title="home-lock")


@app.on_event("startup")
def _startup() -> None:
    if not config.ADMIN_KEY:
        raise RuntimeError("Set HOMELOCK_ADMIN_KEY before starting the server")
    init_db()


def admin(x_admin_key: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_admin_key, config.ADMIN_KEY):
        raise HTTPException(401, "bad admin key")


def device(x_device_key: str = Header(default="")) -> str:
    with connect() as db:
        row = db.execute("SELECT id FROM devices WHERE key = ?", (x_device_key,)).fetchone()
    if not row:
        raise HTTPException(401, "unknown device")
    return row["id"]


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def is_banned(db, domain: str) -> bool:
    parts = domain.split(".")
    candidates = [".".join(parts[i:]) for i in range(len(parts) - 1)] or [domain]
    q = ",".join("?" * len(candidates))
    return db.execute(f"SELECT 1 FROM banned_domains WHERE domain IN ({q})", candidates).fetchone() is not None


# ---- client API (extension / android app) ----

class PageReport(BaseModel):
    url: str
    title: str = ""
    text: str = Field(default="", max_length=config.MAX_TEXT_CHARS)


@app.post("/api/check")
def check(report: PageReport, device_id: str = Depends(device)) -> dict:
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
        if verdict != "allow":
            db.execute(
                "INSERT INTO events (device_id, ts, url, domain, title, score, verdict, reasons)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (device_id, now(), report.url, domain, report.title, score, verdict, "; ".join(reasons)),
            )
    return {"verdict": verdict, "score": score, "reasons": reasons}


@app.get("/api/banned")
def banned(_: str = Depends(device)) -> dict:
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
            "INSERT INTO devices VALUES (?,?,?,?,?)", (dev_id, body.name, body.kind, key, now())
        )
    return {"id": dev_id, "key": key}


class Ban(BaseModel):
    domain: str
    reason: str = "manual"


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
    sql, args = "SELECT * FROM events", []
    if verdict:
        sql += " WHERE verdict = ?"
        args.append(verdict)
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(min(limit, 1000))
    with connect() as db:
        return [dict(r) for r in db.execute(sql, args).fetchall()]
