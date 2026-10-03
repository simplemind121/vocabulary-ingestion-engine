import pytest

from app.db import SessionLocal
from app.models import ReviewTask, VocabularyEntry
from app.services.extraction import extract_native_blocks
from app.services.gold import build_gold_dataset
from app.services.review import resolve_review_task
from app.services.segmentation import segment_source_entries
from app.services.structured_extraction import extract_canonical_fields
from app.services.validation import validate_canonical_entries


def _prepare(client, sample_pdf_bytes):
    response = client.post("/api/v1/documents", files={"file": ("gold.pdf", sample_pdf_bytes, "application/pdf")})
    assert response.status_code == 200
    return response.json()["run_id"]


def test_gold_publisher_accepts_only_verified_records(client, sample_pdf_bytes):
    run_id = _prepare(client, sample_pdf_bytes)
    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        segment_source_entries(db, run_id)
        extract_canonical_fields(db, run_id)
        validate_canonical_entries(db, run_id)
        gold = build_gold_dataset(db, run_id)
        assert gold["record_count"] >= 1
        assert all(record["verification_status"] in {"AUTO_VERIFIED", "HUMAN_VERIFIED"} for record in gold["records"])
    finally:
        db.close()


def test_gold_publisher_blocks_unresolved_records(client, sample_pdf_bytes):
    run_id = _prepare(client, sample_pdf_bytes)
    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        segment_source_entries(db, run_id)
        extract_canonical_fields(db, run_id)
        entry = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id).first()
        assert entry is not None
        entry.verification_status = "REVIEW_REQUIRED"
        db.commit()
        with pytest.raises(ValueError, match="unresolved"):
            build_gold_dataset(db, run_id)
    finally:
        db.close()


def test_human_resolution_promotes_entry_to_human_verified(client, sample_pdf_bytes):
    run_id = _prepare(client, sample_pdf_bytes)
    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        segment_source_entries(db, run_id)
        extract_canonical_fields(db, run_id)
        entry = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id).first()
        assert entry is not None
        entry.lemma = "123-invalid"
        db.commit()
        validate_canonical_entries(db, run_id)
        task = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.status == "OPEN").first()
        assert task is not None
        result = resolve_review_task(db, task.id, resolution={"lemma": "verified"}, reviewer_id="test-reviewer")
        assert result["verification_status"] == "HUMAN_VERIFIED"
        assert db.get(ReviewTask, task.id).status == "RESOLVED"
    finally:
        db.close()
