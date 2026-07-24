from starlette.testclient import TestClient

from app.main import app


def test_root() -> None:
    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["name"] == "crate-digger"


def test_health() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # Never leaks secret values — only booleans about presence.
    assert set(body) == {"status", "env", "nimble_configured", "seed_configured"}
