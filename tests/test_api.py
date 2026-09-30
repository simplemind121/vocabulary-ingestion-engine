from fastapi.testclient import TestClient

from app.main import app
from app.settings import get_settings

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_liveness_and_readiness_are_separate():
    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["checks"] == {
        "database": "ok",
        "redis": "not_configured",
        "storage": "ok",
    }


def test_api_key_protects_api_routes(monkeypatch):
    monkeypatch.setenv("VIE_API_KEY", "test-secret-token")
    get_settings.cache_clear()
    try:
        unauthorized = client.post("/api/v1/gold/preflight", json={})
        authorized = client.post(
            "/api/v1/gold/preflight",
            json={},
            headers={"Authorization": "Bearer test-secret-token"},
        )
    finally:
        get_settings.cache_clear()

    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == "Bearer"
    assert authorized.status_code == 200


def test_gold_preflight_passes_only_with_zero_unresolved_state():
    response = client.post("/api/v1/gold/preflight", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "PASS"
    assert response.json()["publish_allowed"] is True


def test_gold_preflight_blocks_unresolved_records():
    response = client.post("/api/v1/gold/preflight", json={"unresolved_records": 1})
    body = response.json()
    assert body["status"] == "FAIL"
    assert body["publish_allowed"] is False
    assert "unresolved_records" in body["blocking_failures"]
