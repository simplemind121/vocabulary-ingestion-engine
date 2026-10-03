from app.db import SessionLocal
from app.models import SourceBlock, SourceEntry, VocabularyEntry
from app.services.segmentation import segment_source_entries


def test_g2_prefers_accepted_reviewed_ocr_text(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("reviewed-g2.pdf", sample_pdf_bytes, "application/pdf")},
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
            raw_text="medicafion [wrong] n. wrong",
            confidence=0.42,
            bbox={"x1": 0.1, "y1": 0.1, "x2": 0.9, "y2": 0.2, "unit": "normalized"},
            source_engine="ocr:fake",
            source_engine_version="1",
            metadata_json={
                "reviewed_text": "medication [ˌmedɪˈkeɪʃn] n. medicine",
                "human_ocr_review": {"decision": "ACCEPT", "reviewer_id": "human-1"},
            },
        )
        db.add(block)
        db.commit()

        result = segment_source_entries(db, run_id)
        entry = db.query(SourceEntry).filter(SourceEntry.processing_run_id == run_id).one()
        vocab = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id).one()

        assert result["source_entries"] == 1
        assert entry.raw_text.startswith("medication")
        assert "medicafion" not in entry.raw_text
        assert vocab.lemma == "medication"
        db.refresh(block)
        assert block.raw_text.startswith("medicafion")
    finally:
        db.close()


def test_g2_ignores_unaccepted_reviewed_text(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("unaccepted-g2.pdf", sample_pdf_bytes, "application/pdf")},
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
            raw_text="originalword n. source",
            confidence=0.42,
            bbox={"x1": 0.1, "y1": 0.1, "x2": 0.9, "y2": 0.2, "unit": "normalized"},
            source_engine="ocr:fake",
            source_engine_version="1",
            metadata_json={
                "reviewed_text": "replacement n. unsafe",
                "human_ocr_review": {"decision": "REJECT", "reviewer_id": "human-1"},
            },
        )
        db.add(block)
        db.commit()

        segment_source_entries(db, run_id)
        vocab = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id).one()
        assert vocab.lemma == "originalword"
    finally:
        db.close()
