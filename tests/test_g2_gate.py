from app.db import SessionLocal
from app.services.extraction import extract_native_blocks
from app.services.gates import evaluate_g2_entry_segmentation
from app.services.segmentation import segment_source_entries


def test_g2_passes_for_linked_nonempty_source_entries(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("g2.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        segment_source_entries(db, run_id)
        result = evaluate_g2_entry_segmentation(db, run_id)
        assert result["status"] == "PASS"
        assert result["metrics"]["source_entry_count"] >= 1
        assert result["metrics"]["empty_entries"] == 0
        assert result["metrics"]["unlinked_entries"] == 0
    finally:
        db.close()
