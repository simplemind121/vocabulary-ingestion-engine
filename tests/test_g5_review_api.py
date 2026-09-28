from app.db import SessionLocal
from app.models import ProvenanceRecord, ReviewTask, SourceBlock, VocabularyEntry
from app.services.extraction import extract_native_blocks
from app.services.gates import evaluate_g5_review_resolution
from app.services.segmentation import segment_source_entries
from app.services.structured_extraction import extract_canonical_fields


def _prepared_run(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("g5-review.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    db = SessionLocal()
    extract_native_blocks(db, run_id)
    segment_source_entries(db, run_id)
    extract_canonical_fields(db, run_id)
    return db, run_id


def test_g5_vocabulary_review_api_records_audit_and_closes_gate(client, sample_pdf_bytes):
    db, run_id = _prepared_run(client, sample_pdf_bytes)
    try:
        entry = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id).first()
        assert entry is not None
        entry.verification_status = "REVIEW_REQUIRED"
        task = ReviewTask(
            processing_run_id=run_id,
            reason_code="G4_VALIDATION_FAILED",
            target_entity_type="VocabularyEntry",
            target_entity_id=entry.id,
            target_field_path="lemma",
            source_context={"raw_text": "source evidence"},
            candidate_values=[],
        )
        db.add(task)
        db.commit()
        task_id = task.id
        old_lemma = entry.lemma
    finally:
        db.close()

    queue = client.get(f"/api/v1/runs/{run_id}/reviews", params={"status": "OPEN"})
    assert queue.status_code == 200
    assert queue.json()["count"] == 1
    assert queue.json()["items"][0]["id"] == task_id

    response = client.post(
        f"/api/v1/reviews/{task_id}/resolve",
        json={
            "reviewer_id": "qa-reviewer",
            "decision": "ACCEPT",
            "lemma": f"{old_lemma}-reviewed",
            "notes": "verified against source page",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["verification_status"] == "HUMAN_VERIFIED"
    assert payload["g5"]["status"] == "PASS"

    db = SessionLocal()
    try:
        task = db.get(ReviewTask, task_id)
        entry = db.get(VocabularyEntry, payload["entry_id"])
        assert task is not None and task.status == "RESOLVED"
        assert entry is not None and entry.verification_status == "HUMAN_VERIFIED"
        audit = task.candidate_values[0]
        assert audit["reviewer_id"] == "qa-reviewer"
        assert audit["decision"] == "ACCEPT"
        assert audit["resolved_at"]
        provenance = (
            db.query(ProvenanceRecord)
            .filter(
                ProvenanceRecord.processing_run_id == run_id,
                ProvenanceRecord.target_entity_id == entry.id,
                ProvenanceRecord.target_field_path == "lemma",
                ProvenanceRecord.provenance_type == "HUMAN_REVIEW",
            )
            .one()
        )
        assert provenance.metadata_json["review_task_id"] == task_id
        assert provenance.metadata_json["reviewer_id"] == "qa-reviewer"
        assert evaluate_g5_review_resolution(db, run_id)["status"] == "PASS"
    finally:
        db.close()


def test_g5_source_block_review_preserves_raw_ocr_and_stores_reviewed_text(client, sample_pdf_bytes):
    db, run_id = _prepared_run(client, sample_pdf_bytes)
    try:
        block = db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id).first()
        assert block is not None
        raw_text = block.raw_text
        task = ReviewTask(
            processing_run_id=run_id,
            reason_code="LOW_OCR_CONFIDENCE",
            target_entity_type="SourceBlock",
            target_entity_id=block.id,
            target_field_path="raw_text",
            source_context={"raw_text": raw_text},
            candidate_values=[],
        )
        db.add(task)
        db.commit()
        task_id = task.id
        block_id = block.id
    finally:
        db.close()

    corrected = "human reviewed source text"
    response = client.post(
        f"/api/v1/reviews/{task_id}/resolve",
        json={
            "reviewer_id": "ocr-reviewer",
            "decision": "ACCEPT",
            "corrected_text": corrected,
        },
    )
    assert response.status_code == 200
    assert response.json()["reviewed_text"] == corrected

    db = SessionLocal()
    try:
        block = db.get(SourceBlock, block_id)
        assert block is not None
        assert block.raw_text == raw_text
        assert block.metadata_json["reviewed_text"] == corrected
        provenance = (
            db.query(ProvenanceRecord)
            .filter(
                ProvenanceRecord.processing_run_id == run_id,
                ProvenanceRecord.target_entity_type == "SourceBlock",
                ProvenanceRecord.target_entity_id == block_id,
                ProvenanceRecord.provenance_type == "HUMAN_REVIEW",
            )
            .one()
        )
        assert provenance.metadata_json["raw_ocr_text"] == raw_text
        assert provenance.source_text == corrected
    finally:
        db.close()
