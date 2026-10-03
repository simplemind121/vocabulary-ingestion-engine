import fitz

from app.db import SessionLocal
from app.services.document_analysis import analyze_text_layer


def _blank_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page()
    payload = doc.tobytes()
    doc.close()
    return payload


def test_native_text_document_is_classified(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("native.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        result = analyze_text_layer(db, run_id)
        assert result["document_mode"] == "NATIVE_TEXT"
        assert result["native_text_page_ratio"] == 1.0
    finally:
        db.close()


def test_textless_document_is_classified_as_scanned(client):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("scan.pdf", _blank_pdf(), "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        result = analyze_text_layer(db, run_id)
        assert result["document_mode"] == "SCANNED"
        assert result["native_text_pages"] == 0
    finally:
        db.close()
