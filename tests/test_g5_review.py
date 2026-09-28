import pytest

from app.db import SessionLocal
from app.models import ProvenanceRecord, ReviewTask, VocabularyEntry
from app.services.extraction import extract_native_blocks
from app.services.gates import evaluate_g4_validation, evaluate_g5_review_resolution
from app.services.review import resolve_review_task
from app.services.segmentation import segment_source_entries
from app.services.structured_extraction import extract_canonical_fields
from app.services.validation import validate_canonical_entries


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


def test_g4_review_queue_resolves_to_human_verified_and_g5_pass(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("g5-e2e.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        segment_source_entries(db, run_id)
        extract_canonical_fields(db, run_id)

        entry = (
            db.query(VocabularyEntry)
            .filter(VocabularyEntry.processing_run_id == run_id)
            .first()
        )
        assert entry is not None
        entry.lemma = "1nvalid"
        db.commit()

        validation = validate_canonical_entries(db, run_id)
        assert validation["validation_issues"] >= 1
        g4 = evaluate_g4_validation(db, run_id)
        assert g4["status"] == "REVIEW_REQUIRED"

        task = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.processing_run_id == run_id,
                ReviewTask.status == "OPEN",
            )
            .first()
        )
        assert task is not None
        assert task.reason_code == "G4_VALIDATION_FAILED"
        g5_before = evaluate_g5_review_resolution(db, run_id)
        assert g5_before["status"] == "REVIEW_REQUIRED"

        resolved = resolve_review_task(
            db,
            task.id,
            resolution={"decision": "ACCEPT", "lemma": "abandon", "notes": "source checked"},
            reviewer_id="reviewer-1",
        )
        assert resolved["verification_status"] == "HUMAN_VERIFIED"

        db.refresh(entry)
        assert entry.lemma == "abandon"
        assert entry.verification_status == "HUMAN_VERIFIED"
        human_provenance = (
            db.query(ProvenanceRecord)
            .filter(
                ProvenanceRecord.processing_run_id == run_id,
                ProvenanceRecord.target_entity_type == "VocabularyEntry",
                ProvenanceRecord.target_entity_id == entry.id,
                ProvenanceRecord.target_field_path == "lemma",
                ProvenanceRecord.provenance_type == "HUMAN_REVIEW",
            )
            .one()
        )
        assert human_provenance.metadata_json["reviewer_id"] == "reviewer-1"

        g5_after = evaluate_g5_review_resolution(db, run_id)
        assert g5_after["status"] == "PASS"
        assert g5_after["metrics"]["open_review_tasks"] == 0
        assert g5_after["metrics"]["human_verified_entries"] >= 1
    finally:
        db.close()


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
