import fitz

from app.db import SessionLocal
from app.models import ReviewTask
from app.services.gates import evaluate_g1_document_representation
from app.services.pipeline import run_pipeline
from app.services.review import resolve_review_task


def test_hybrid_no_text_page_requires_explicit_human_classification(client):
    document = fitz.open()
    native = document.new_page()
    native.insert_text((72, 72), "sample* [ˈsɑːmpl] n. sample vocabulary definition")
    document.new_page()
    payload = document.tobytes()
    document.close()
    response = client.post(
        "/api/v1/documents",
        files={"file": ("hybrid-no-text.pdf", payload, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        result = run_pipeline(db, run_id, publish=False)
        assert result["status"] == "REVIEW_REQUIRED"
        assert result["blocked_gate"] == "G1"
        task = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.processing_run_id == run_id,
                ReviewTask.reason_code == "NO_TEXT_LAYER",
            )
            .one()
        )
        resolution = resolve_review_task(
            db,
            task.id,
            resolution={"decision": "ACCEPT", "classification": "NON_TEXT_PAGE"},
            reviewer_id="human-reviewer",
        )
        assert resolution["verification_status"] == "HUMAN_VERIFIED"
        assert evaluate_g1_document_representation(db, run_id)["status"] == "PASS"
    finally:
        db.close()
