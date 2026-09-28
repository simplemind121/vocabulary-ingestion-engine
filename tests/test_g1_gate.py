from app.db import SessionLocal
from app.services.extraction import extract_native_blocks
from app.services.gates import evaluate_g1_document_representation


def test_g1_passes_for_persisted_native_source_blocks(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("g1.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        result = evaluate_g1_document_representation(db, run_id)
        assert result["status"] == "PASS"
        assert result["metrics"]["page_representation_coverage"] == 1.0
        assert result["metrics"]["invalid_geometry_blocks"] == 0
    finally:
        db.close()
