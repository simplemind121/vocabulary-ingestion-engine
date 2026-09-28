import fitz

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.db import SessionLocal
from app.idr import BoundingBox, TextBlock
from app.services.pipeline import run_pipeline


class PipelineFakeOcr:
    name = "pipeline-fake"
    version = "1.0"

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        return OcrPageResult(
            page_number=page.page_number,
            blocks=[
                TextBlock(
                    text="medication* [ˌmedɪˈkeɪʃn]\nn. 药；药物",
                    bbox=BoundingBox(0.1, 0.1, 0.9, 0.3),
                    reading_order=0,
                    confidence=0.99,
                )
            ],
            engine_name=self.name,
            engine_version=self.version,
            metadata={"fixture": "pipeline"},
        )


def test_scanned_pipeline_uses_configured_ocr_adapter_and_passes_g1(client):
    doc = fitz.open()
    doc.new_page()
    payload = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/documents",
        files={"file": ("scan-e2e.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        result = run_pipeline(db, run_id, publish=False, ocr_adapter=PipelineFakeOcr())
    finally:
        db.close()

    assert result["status"] != "OCR_REQUIRED"
    stage_names = [stage["stage"] for stage in result["stages"]]
    assert "ocr_extraction" in stage_names
    g1 = next(stage["result"] for stage in result["stages"] if stage["stage"] == "G1")
    assert g1["status"] == "PASS"
    assert g1["metrics"]["page_representation_coverage"] == 1.0
