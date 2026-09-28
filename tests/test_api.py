from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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
