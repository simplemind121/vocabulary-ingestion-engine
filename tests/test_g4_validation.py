from app.db import SessionLocal
from app.models import ReviewTask, VocabularyEntry
from app.services.extraction import extract_native_blocks
from app.services.gates import evaluate_g4_validation
from app.services.segmentation import segment_source_entries
from app.services.structured_extraction import extract_canonical_fields
from app.services.validation import validate_canonical_entries


def test_g4_passes_after_clean_entries_are_auto_verified(client, sample_pdf_bytes):
    response = client.post("/api/v1/documents", files={"file": ("g4.pdf", sample_pdf_bytes, "application/pdf")})
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        segment_source_entries(db, run_id)
        extract_canonical_fields(db, run_id)
        validate_canonical_entries(db, run_id)
        result = evaluate_g4_validation(db, run_id)
        assert result["status"] == "PASS"
        assert result["metrics"]["unresolved_entries"] == 0
    finally:
        db.close()


def test_g4_requires_review_for_invalid_lemma(client, sample_pdf_bytes):
    response = client.post("/api/v1/documents", files={"file": ("g4-review.pdf", sample_pdf_bytes, "application/pdf")})
    assert response.status_code == 200
    run_id = response.json()["run_id"]
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
        result = evaluate_g4_validation(db, run_id)
        assert result["status"] == "REVIEW_REQUIRED"
        review = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.reason_code == "G4_VALIDATION_FAILED").first()
        assert review is not None
        assert review.status == "OPEN"
    finally:
        db.close()
