import pytest

from app.db import SessionLocal
from app.services.gates import evaluate_g5_review_resolution
from app.services.review import resolve_review_task


def test_g5_passes_when_run_has_no_open_review_tasks(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("g5.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        result = evaluate_g5_review_resolution(db, run_id)
        assert result["gate"] == "G5"
        assert result["status"] == "PASS"
        assert result["metrics"]["open_review_tasks"] == 0
    finally:
        db.close()


def test_review_queue_api_returns_empty_queue_for_clean_run(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("g5-api.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    queue = client.get(f"/api/v1/runs/{run_id}/reviews")
    assert queue.status_code == 200
    payload = queue.json()
    assert payload["run_id"] == run_id
    assert payload["count"] == 0
    assert payload["items"] == []


def test_review_queue_api_rejects_unknown_run(client):
    response = client.get("/api/v1/runs/missing/reviews")
    assert response.status_code == 404


def test_review_resolution_api_rejects_unknown_task(client):
    response = client.post(
        "/api/v1/reviews/missing/resolve",
        json={"reviewer_id": "reviewer-1", "decision": "ACCEPT"},
    )
    assert response.status_code == 404


def test_review_service_rejects_unknown_task():
    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="review task not found"):
            resolve_review_task(
                db,
                "missing",
                resolution={"decision": "ACCEPT"},
                reviewer_id="reviewer-1",
            )
    finally:
        db.close()
