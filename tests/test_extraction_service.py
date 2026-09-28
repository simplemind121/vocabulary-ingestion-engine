from app.db import SessionLocal
from app.models import SourceBlock
from app.services.extraction import extract_native_blocks


def test_native_extraction_persists_source_blocks(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("native.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        result = extract_native_blocks(db, run_id)
        assert result["source_blocks"] >= 1

        blocks = db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id).all()
        assert any("abandon" in (block.raw_text or "") for block in blocks)

        repeated = extract_native_blocks(db, run_id)
        assert repeated["reused"] is True
        assert repeated["source_blocks"] == result["source_blocks"]
    finally:
        db.close()
