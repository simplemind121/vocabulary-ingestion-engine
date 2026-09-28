import fitz

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.db import SessionLocal
from app.idr import BoundingBox, TextBlock
from app.models import Page, SourceBlock
from app.services.pipeline import run_pipeline


class RecordingOcr:
    name = "recording"
    version = "1.0"

    def __init__(self):
        self.pages = []

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        self.pages.append(page.page_number)
        return OcrPageResult(
            page_number=page.page_number,
            blocks=[TextBlock(
                text="medication* [medication] n. medicine",
                bbox=BoundingBox(0.1, 0.1, 0.9, 0.2),
                reading_order=0,
                confidence=0.99,
            )],
            engine_name=self.name,
            engine_version=self.version,
        )


def test_hybrid_pipeline_ocr_only_scanned_pages(client):
    doc = fitz.open()
    native = doc.new_page()
    native.insert_text((72, 72), "native vocabulary page with enough meaningful text")
    doc.new_page()
    payload = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/documents",
        files={"file": ("hybrid.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    adapter = RecordingOcr()

    db = SessionLocal()
    try:
        result = run_pipeline(db, run_id, publish=False, ocr_adapter=adapter)
        blocks = db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id).all()
        page_numbers = {page.id: page.page_number for page in db.query(Page).all()}
        ocr_pages = {
            page_numbers[block.page_id]
            for block in blocks
            if block.source_engine.startswith("ocr:")
        }
        native_pages = {
            page_numbers[block.page_id]
            for block in blocks
            if not block.source_engine.startswith("ocr:")
        }
    finally:
        db.close()

    assert adapter.pages == [2]
    analysis = result["stages"][0]["result"]
    assert analysis["document_mode"] == "HYBRID"
    assert ocr_pages == {2}
    assert native_pages == {1}
    g1 = next(stage["result"] for stage in result["stages"] if stage["stage"] == "G1")
    assert g1["status"] == "PASS"
    assert g1["metrics"]["page_representation_coverage"] == 1.0
