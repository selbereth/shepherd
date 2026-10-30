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


def test_feed_parse_and_check(client, dev, monkeypatch):
    from app import feeds

    text = "# c\n127.0.0.1 localhost\n0.0.0.0 adult-feed-one.test\n0.0.0.0 www.adult-feed-two.test # x\nplain-three.test\n"
    assert feeds.parse(text) == {"adult-feed-one.test", "adult-feed-two.test", "plain-three.test"}

    domains = {f"feed{i}.test" for i in range(150)} | {"adult-feed-one.test"}
    monkeypatch.setattr(config, "FEED_URL", "http://x")
    monkeypatch.setattr(feeds, "_download", lambda url: "\n".join("0.0.0.0 " + d for d in domains))
    assert client.post("/admin/feeds/adult/refresh", headers=ADMIN).json()["count"] == 151
    r = check(client, dev, "https://cdn.adult-feed-one.test/page")
    assert r["verdict"] == "block" and r["reasons"] == ["on adult site list"]

    monkeypatch.setattr(feeds, "_download", lambda url: "0.0.0.0 only-one.test")
    assert client.post("/admin/feeds/adult/refresh", headers=ADMIN).status_code == 502
    assert check(client, dev, "https://adult-feed-one.test")["verdict"] == "block"  # old list kept


def test_adblock_list_version_allowlist_and_proceed(client, dev, monkeypatch):
    from app import feeds

    assert client.get("/api/adblock").status_code == 401
    domains = {f"ads{i}.test" for i in range(150)} | {"tracker.test", "cdn.keepme.test"}
    monkeypatch.setattr(config, "ADS_FEED_URL", "http://x")
    monkeypatch.setattr(feeds, "_download", lambda url: "\n".join("0.0.0.0 " + d for d in domains))
    assert client.post("/admin/feeds/ads/refresh", headers=ADMIN).json()["count"] == 152

    first = client.get("/api/adblock", headers=dev).json()
    assert "tracker.test" in first["domains"] and "cdn.keepme.test" in first["domains"]
    # unchanged -> no list sent
    assert client.get("/api/adblock?since=" + first["version"], headers=dev).json()["domains"] is None

    # allowlisting a parent domain removes it (and subdomains) and bumps the version
    client.post("/admin/adblock/allow", json={"domain": "keepme.test"}, headers=ADMIN)
    second = client.get("/api/adblock?since=" + first["version"], headers=dev).json()
    assert second["version"] != first["version"]
    assert "cdn.keepme.test" not in second["domains"] and "tracker.test" in second["domains"]

    # ads domains don't hard-block on the server
    assert check(client, dev, "https://tracker.test/")["verdict"] == "allow"

    client.post("/api/proceed", json={"url": "https://tracker.test/x"}, headers=dev)
    ev = client.get("/admin/events?verdict=allow", headers=ADMIN).json()
    assert any(e["reasons"] == "proceeded past ad/tracker/malware block" for e in ev)


def test_content_scoring_signals(client, dev):
    def post(url, title, text, rating=""):
        return client.post("/api/check", json={"url": url, "title": title, "text": text, "rating": rating}, headers=dev).json()

    # Self-labeled adult page with almost no text is still blocked.
    r = post("https://unlisted-site.example/", "Videos", "Sign in Categories", "RTA-5042-1996-1400-1577-RTA")
    assert r["verdict"] == "block" and "labeled adult" in r["reasons"][0]

    # A page saturated with explicit terms blocks; a news article mentioning a few only warns.
    assert post("https://unlisted-two.example/", "x", "porn xxx hentai nsfw " * 10)["verdict"] == "block"
    news = "State passes porn age-check law. Critics say the xxx rules are vague and the porn industry will resist. " * 1
    assert post("https://news.example/a", "Law", news)["verdict"] in ("warn", "allow")
    assert post("https://news.example/b", "Recipes", "pasta " * 200, "general")["verdict"] == "allow"


def test_computers_are_told_apart(client):
    key = client.post("/admin/devices", json={"name": "shared"}, headers=ADMIN).json()["key"]
    a = {"X-Device-Key": key, "X-Instance": "aaaaaaaa-1111"}
    b = {"X-Device-Key": key, "X-Instance": "bbbbbbbb-2222"}
    for h, host in ((a, "one.example"), (b, "two.example")):
        client.post("/api/check", json={"url": f"https://{host}/"}, headers=h)
    # bad IDs are ignored rather than rejected
    client.post("/api/check", json={"url": "https://three.example/"}, headers={"X-Device-Key": key, "X-Instance": "bad id!"})

    inst = {i["id"]: i for i in client.get("/admin/instances", headers=ADMIN).json()}
    assert {"aaaaaaaa-1111", "bbbbbbbb-2222"} <= inst.keys() and "bad id!" not in inst

    assert client.patch("/admin/instances/aaaaaaaa-1111", json={"label": "Living room PC"}, headers=ADMIN).status_code == 200
    assert client.patch("/admin/instances/nope", json={"label": "x"}, headers=ADMIN).status_code == 404
    ev = {e["domain"]: e for e in client.get("/admin/events", headers=ADMIN).json()}
    assert ev["one.example"]["instance_label"] == "Living room PC"
    assert ev["two.example"]["instance_id"] == "bbbbbbbb-2222" and ev["two.example"]["instance_label"] == ""
    assert ev["three.example"]["instance_id"] is None

    # another device can't claim an existing computer ID
    other = client.post("/admin/devices", json={"name": "other"}, headers=ADMIN).json()["key"]
    client.post("/api/check", json={"url": "https://four.example/"}, headers={"X-Device-Key": other, "X-Instance": "aaaaaaaa-1111"})
    assert {i["id"]: i["device_id"] for i in client.get("/admin/instances", headers=ADMIN).json()}["aaaaaaaa-1111"] == inst["aaaaaaaa-1111"]["device_id"]
