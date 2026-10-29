import pytest
from fastapi.testclient import TestClient

from app.main import app

ADMIN = {"X-Admin-Key": "test-admin"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def dev(client):
    key = client.post("/admin/devices", json={"name": "t"}, headers=ADMIN).json()["key"]
    return {"X-Device-Key": key}


def check(client, dev, url, text=""):
    return client.post("/api/check", json={"url": url, "text": text}, headers=dev).json()


def test_requires_keys(client):
    assert client.post("/api/check", json={"url": "https://a.com"}).status_code == 401
    assert client.get("/admin/events").status_code == 401


def test_clean_page_allowed(client, dev):
    assert check(client, dev, "https://example.com", "pasta recipes")["verdict"] == "allow"


def test_bad_content_flagged(client, dev):
    r = check(client, dev, "https://x.example", "nsfw porn hentai nude")
    assert r["verdict"] in ("warn", "block")
    assert r["reasons"]


def test_banned_domain_includes_subdomains(client, dev):
    client.post("/admin/banned", json={"domain": "bad.test"}, headers=ADMIN)
    assert check(client, dev, "https://www.sub.bad.test/x")["verdict"] == "block"
    assert "bad.test" in client.get("/api/banned", headers=dev).json()["domains"]
    client.delete("/admin/banned/bad.test", headers=ADMIN)
    assert check(client, dev, "https://bad.test")["verdict"] == "allow"


# ---- alerts, heartbeat, dashboard endpoints ----

from app import alerts, config  # noqa: E402
from app.db import connect  # noqa: E402


@pytest.fixture()
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(alerts, "send", lambda title, body, priority="default": calls.append((title, body, priority)))
    alerts._last_sent.clear()
    return calls


def test_block_triggers_one_alert_with_cooldown(client, dev, sent):
    client.post("/admin/banned", json={"domain": "alert.test"}, headers=ADMIN)
    check(client, dev, "https://alert.test/a")
    check(client, dev, "https://alert.test/b")  # same device+domain: suppressed by cooldown
    assert len(sent) == 1
    assert "alert.test" in sent[0][0] and sent[0][2] == "high"


def test_warn_alerts_only_when_enabled(client, dev, sent, monkeypatch):
    text = "nsfw porn hentai nude"
    monkeypatch.setattr(config, "ALERT_ON", "block")
    check(client, dev, "https://w1.example", text)
    assert sent == []
    monkeypatch.setattr(config, "ALERT_ON", "warn")
    check(client, dev, "https://w2.example", text)
    assert len(sent) == 1


def test_offline_and_back_online(client, sent, monkeypatch):
    key = client.post("/admin/devices", json={"name": "laptop"}, headers=ADMIN).json()
    h = {"X-Device-Key": key["key"]}
    client.get("/api/banned", headers=h)  # heartbeat
    alerts.check_offline()
    assert sent == []
    with connect() as db:
        db.execute("UPDATE devices SET last_seen = last_seen - 3600 WHERE id = ?", (key["id"],))
    alerts.check_offline()
    alerts.check_offline()  # only one alert until it returns
    assert [s[0] for s in sent] == ["laptop stopped checking in"]
    client.get("/api/banned", headers=h)
    alerts.check_offline()
    assert sent[-1][0] == "laptop is back online"


def test_admin_lists_and_stats(client, dev):
    devices = client.get("/admin/devices", headers=ADMIN).json()
    assert devices and "key" not in devices[0]
    assert all(d["last_seen"] for d in devices if d["name"] == "t")
    assert isinstance(client.get("/admin/banned", headers=ADMIN).json(), list)
    stats = client.get("/admin/stats", headers=ADMIN).json()
    assert {"period", "top_domains", "alert_channels"} <= stats.keys()
    ev = client.get("/admin/events?verdict=block", headers=ADMIN).json()
    assert ev and "device_name" in ev[0]


def test_test_alert_requires_channel(client, monkeypatch):
    for name in ("NTFY_URL", "WEBHOOK_URL", "SMTP_HOST"):
        monkeypatch.setattr(config, name, "")
    assert client.post("/admin/alerts/test", headers=ADMIN).status_code == 400


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Shepherd" in r.text


def test_allowed_visits_are_logged(client, dev):
    r = client.post("/api/check", json={"url": "https://example.org/", "title": "hi", "text": "hello"}, headers=dev)
    assert r.json()["verdict"] == "allow"
    ev = client.get("/admin/events?verdict=allow", headers=ADMIN).json()
    assert any(e["domain"] == "example.org" for e in ev)


def test_days_filter(client, dev):
    client.post("/api/check", json={"url": "https://old.test/", "title": "", "text": ""}, headers=dev)
    with connect() as db:
        db.execute("UPDATE events SET ts = ts - 10 * 86400 WHERE domain = 'old.test'")
    recent = client.get("/admin/events?days=7", headers=ADMIN).json()
    assert all(e["domain"] != "old.test" for e in recent)
    assert any(e["domain"] == "old.test" for e in client.get("/admin/events", headers=ADMIN).json())
    assert client.get("/admin/stats?days=30", headers=ADMIN).json()["period"]["allow"] >= 1


def test_known_bad_sites_are_banned_and_flagged(client, dev):
    domains = client.get("/api/banned", headers=dev).json()["domains"]
    assert "pornhub.com" in domains
    r = client.post("/api/check", json={"url": "https://www.some-new-porn-site.net/", "title": "", "text": ""}, headers=dev)
    assert r.json()["verdict"] == "block"
