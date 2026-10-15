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


def _scan_with_hidden_text(pages: int = 2) -> bytes:
    """Pages that are one picture each, with a scanner's invisible OCR text over them."""
    picture = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 80), False)
    picture.clear_with(230)
    doc = fitz.open()
    for number in range(pages):
        page = doc.new_page(width=300, height=400)
        page.insert_image(page.rect, pixmap=picture)
        page.insert_text((30, 60), f"Unit {number + 1} Present continuous", fontsize=12, render_mode=3)
        page.insert_text((30, 90), "I am doing something now.", fontsize=12, render_mode=3)
    payload = doc.tobytes()
    doc.close()
    return payload


def test_a_hidden_scanner_text_layer_does_not_make_a_scan_native(client):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("captured.pdf", _scan_with_hidden_text(), "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        result = analyze_text_layer(db, run_id)
        assert result["document_mode"] == "SCANNED"
        assert result["hidden_text_layer_pages"] == 2
        assert result["native_text_pages"] == 0
        assert all(page["native_char_count"] > 20 for page in result["pages"])
    finally:
        db.close()


def test_the_hidden_layer_is_read_as_rows_with_page_relative_boxes(tmp_path):
    from app.adapters.consensus import PdfTextLayerReader
    from app.adapters.ocr_base import OcrPageInput

    source = tmp_path / "captured.pdf"
    source.write_bytes(_scan_with_hidden_text(pages=1))
    rows = PdfTextLayerReader().read_rows(OcrPageInput(page_number=1, image_bytes=b"", source_path=str(source)))
    assert [row["text"] for row in rows] == ["Unit 1 Present continuous", "I am doing something now."]
    assert all(0 <= row["x1"] < row["x2"] <= 1 and 0 <= row["y1"] < row["y2"] <= 1 for row in rows)
    assert rows[0]["y2"] <= rows[1]["y1"] + 0.01
    # Without the source PDF, or beyond its last page, the reader abstains.
    assert PdfTextLayerReader().read_rows(OcrPageInput(page_number=1, image_bytes=b"")) == []
    assert PdfTextLayerReader().read_rows(OcrPageInput(page_number=9, image_bytes=b"", source_path=str(source))) == []
