from app.db import SessionLocal
from app.models import ProvenanceRecord, ReviewTask, SourceBlock
from app.services.review import resolve_review_task
from app.services.segmentation import _effective_block_text


def test_low_confidence_source_block_review_can_be_accepted(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("ocr-review.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        block = SourceBlock(
            page_id=db.execute(
                __import__("sqlalchemy").text(
                    "select id from pages where document_version_id = "
                    "(select document_version_id from processing_runs where id = :run_id) limit 1"
                ),
                {"run_id": run_id},
            ).scalar_one(),
            processing_run_id=run_id,
            block_type="TEXT",
            reading_order=0,
            raw_text="medicafion",
            confidence=0.42,
            bbox={"x1": 0.1, "y1": 0.1, "x2": 0.9, "y2": 0.2, "unit": "normalized"},
            source_engine="ocr:fake",
            source_engine_version="1",
            metadata_json={},
        )
        db.add(block)
        db.flush()
        task = ReviewTask(
            processing_run_id=run_id,
            reason_code="LOW_OCR_CONFIDENCE",
            status="OPEN",
            target_entity_type="SourceBlock",
            target_entity_id=block.id,
            target_field_path="raw_text",
            source_context={"confidence": 0.42},
            candidate_values=[],
        )
        db.add(task)
        db.commit()

        result = resolve_review_task(
            db,
            task.id,
            resolution={
                "decision": "ACCEPT",
                "corrected_text": "medication",
                "notes": "checked against scan",
            },
            reviewer_id="reviewer-ocr",
        )
        db.refresh(block)
        db.refresh(task)
        provenance = (
            db.query(ProvenanceRecord)
            .filter(
                ProvenanceRecord.processing_run_id == run_id,
                ProvenanceRecord.target_entity_type == "SourceBlock",
                ProvenanceRecord.target_entity_id == block.id,
                ProvenanceRecord.target_field_path == "reviewed_text",
            )
            .one()
        )
        assert result["verification_status"] == "HUMAN_VERIFIED"
        assert result["reviewed_text"] == "medication"
        assert task.status == "RESOLVED"
        assert block.raw_text == "medicafion"
        assert block.metadata_json["reviewed_text"] == "medication"
        assert block.metadata_json["human_ocr_review"]["reviewer_id"] == "reviewer-ocr"
        assert provenance.provenance_type == "HUMAN_REVIEW"
        assert provenance.source_text == "medication"
        assert provenance.metadata_json["raw_ocr_text"] == "medicafion"
    finally:
        db.close()


def test_rejected_source_block_review_stays_escalated(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("ocr-reject.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        page_id = db.execute(
            __import__("sqlalchemy").text(
                "select id from pages where document_version_id = "
                "(select document_version_id from processing_runs where id = :run_id) limit 1"
            ),
            {"run_id": run_id},
        ).scalar_one()
        block = SourceBlock(
            page_id=page_id,
            processing_run_id=run_id,
            block_type="TEXT",
            reading_order=0,
            raw_text="uncertain",
            confidence=0.2,
            bbox={"x1": 0.1, "y1": 0.1, "x2": 0.9, "y2": 0.2, "unit": "normalized"},
            source_engine="ocr:fake",
            source_engine_version="1",
            metadata_json={},
        )
        db.add(block)
        db.flush()
        task = ReviewTask(
            processing_run_id=run_id,
            reason_code="LOW_OCR_CONFIDENCE",
            status="OPEN",
            target_entity_type="SourceBlock",
            target_entity_id=block.id,
            target_field_path="raw_text",
            source_context={"confidence": 0.2},
            candidate_values=[],
        )
        db.add(task)
        db.commit()

        result = resolve_review_task(
            db,
            task.id,
            resolution={"decision": "REJECT"},
            reviewer_id="reviewer-ocr",
        )
        db.refresh(task)
        assert result["verification_status"] == "REVIEW_REQUIRED"
        assert task.status == "ESCALATED"
    finally:
        db.close()


def test_source_block_review_can_discard_non_text_ocr_noise(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("ocr-discard.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        page_id = db.execute(
            __import__("sqlalchemy").text(
                "select id from pages where document_version_id = "
                "(select document_version_id from processing_runs where id = :run_id) limit 1"
            ),
            {"run_id": run_id},
        ).scalar_one()
        block = SourceBlock(
            page_id=page_id,
            processing_run_id=run_id,
            block_type="TEXT",
            reading_order=0,
            raw_text="ER",
            confidence=0.2,
            bbox={"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2, "unit": "normalized"},
            source_engine="ocr:fake",
            source_engine_version="1",
            metadata_json={},
        )
        db.add(block)
        db.flush()
        task = ReviewTask(
            processing_run_id=run_id,
            reason_code="LOW_OCR_CONFIDENCE",
            status="OPEN",
            target_entity_type="SourceBlock",
            target_entity_id=block.id,
            target_field_path="raw_text",
            source_context={"confidence": 0.2},
            candidate_values=[],
        )
        db.add(task)
        db.commit()

        result = resolve_review_task(
            db,
            task.id,
            resolution={"decision": "DISCARD", "notes": "drawing artifact"},
            reviewer_id="reviewer-ocr",
        )
        db.refresh(block)
        db.refresh(task)

        assert result["verification_status"] == "HUMAN_DISCARDED"
        assert task.status == "RESOLVED"
        assert block.raw_text == "ER"
        assert block.metadata_json["human_ocr_review"]["decision"] == "DISCARD"
        assert _effective_block_text(block) == ""
    finally:
        db.close()
