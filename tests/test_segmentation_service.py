from app.db import SessionLocal
from app.models import SourceEntry, VocabularyEntry
from app.services.extraction import extract_native_blocks
from app.services.segmentation import segment_source_entries


def test_baseline_segmenter_creates_source_and_vocabulary_entries(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("segment.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        result = segment_source_entries(db, run_id)
        assert result["source_entries"] >= 1

        source_entries = db.query(SourceEntry).filter(SourceEntry.processing_run_id == run_id).all()
        vocab_entries = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id).all()
        assert source_entries
        assert vocab_entries
        assert vocab_entries[0].lemma == "abandon"

        repeated = segment_source_entries(db, run_id)
        assert repeated["reused"] is True
        assert repeated["source_entries"] == len(source_entries)
    finally:
        db.close()
