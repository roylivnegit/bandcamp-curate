from starlette.testclient import TestClient

from app.main import app


def test_root_is_not_served() -> None:
    # The legacy server-rendered UI is unregistered while the API is auth-only —
    # see the note in app/main.py. The React frontend takes over GET / next.
    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 404


def test_info() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/info")
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
