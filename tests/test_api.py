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


def test_metrics_exposes_bounded_operational_state_and_request_ids():
    response = client.get("/metrics", headers={"X-Request-ID": "operator-check-1"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "operator-check-1"
    assert response.headers["content-type"].startswith("text/plain")
    assert 'vie_build_info{version="0.1.0-alpha.4"} 1' in response.text
    assert "vie_processing_runs" in response.text
    assert "vie_review_tasks" in response.text
    assert "vie_gate_evaluations" in response.text
    assert "vie_gold_releases_total" in response.text


def test_invalid_request_id_is_not_reflected():
    response = client.get("/health/live", headers={"X-Request-ID": "bad id\nvalue"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad id\nvalue"
    assert len(response.headers["x-request-id"]) == 36


def test_api_key_protects_api_routes(monkeypatch):
    monkeypatch.setenv("VIE_API_KEY", "test-secret-token")
    get_settings.cache_clear()
    try:
        unauthorized = client.post("/api/v1/gold/preflight", json={})
        metrics_unauthorized = client.get("/metrics")
        authorized = client.post(
            "/api/v1/gold/preflight",
            json={},
            headers={"Authorization": "Bearer test-secret-token"},
        )
        metrics_authorized = client.get(
            "/metrics", headers={"Authorization": "Bearer test-secret-token"}
        )
        health = client.get("/health/ready")
    finally:
        get_settings.cache_clear()

    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == "Bearer"
    assert authorized.status_code == 200
    assert metrics_unauthorized.status_code == 401
    assert metrics_authorized.status_code == 200
    assert health.status_code == 200


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
