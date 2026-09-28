from app.db import SessionLocal
from app.services.extraction import extract_native_blocks
from app.services.gates import evaluate_g3_structured_extraction
from app.services.segmentation import segment_source_entries
from app.services.structured_extraction import extract_canonical_fields


def test_g3_passes_when_required_lemma_provenance_exists(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("g3.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        segment_source_entries(db, run_id)
        extract_canonical_fields(db, run_id)
        result = evaluate_g3_structured_extraction(db, run_id)
        assert result["status"] == "PASS"
        assert result["metrics"]["missing_lemma"] == 0
        assert result["metrics"]["missing_lemma_provenance"] == 0
    finally:
        db.close()
