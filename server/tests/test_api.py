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
