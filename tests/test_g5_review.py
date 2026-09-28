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
