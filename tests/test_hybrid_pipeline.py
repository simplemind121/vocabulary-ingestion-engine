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


def test_resumed_run_reuses_native_blocks_once_entries_reference_them(client, sample_pdf_bytes):
    from app.db import SessionLocal
    from app.models import SourceBlock
    from app.services.extraction import extract_native_blocks
    from app.services.segmentation import segment_source_entries

    run_id = client.post(
        "/api/v1/documents", files={"file": ("resume.pdf", sample_pdf_bytes, "application/pdf")}
    ).json()["run_id"]
    db = SessionLocal()
    try:
        assert extract_native_blocks(db, run_id, page_numbers={1})["reused"] is False
        # Before segmentation a selective pass may still rebuild its blocks.
        assert extract_native_blocks(db, run_id, page_numbers={1})["reused"] is False
        segment_source_entries(db, run_id)
        before = sorted(
            block.id for block in db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id)
        )
        assert extract_native_blocks(db, run_id, page_numbers={1})["reused"] is True
        after = sorted(
            block.id for block in db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id)
        )
        assert after == before
    finally:
        db.close()


def test_pipeline_failure_marks_the_run_failed_instead_of_leaving_it_running(
    client, sample_pdf_bytes, monkeypatch
):
    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.db import SessionLocal
    from app.models import ProcessingRun
    from app.services import pipeline

    run_id = client.post(
        "/api/v1/documents", files={"file": ("fail.pdf", sample_pdf_bytes, "application/pdf")}
    ).json()["run_id"]

    def broken(db, run_id, **kwargs):
        db.add(ProcessingRun(id=run_id, document_version_id="missing"))
        db.flush()

    monkeypatch.setattr(pipeline, "extract_native_blocks", broken)
    db = SessionLocal()
    try:
        with pytest.raises(IntegrityError):
            pipeline.run_pipeline(db, run_id)
        db.expire_all()
        run = db.get(ProcessingRun, run_id)
        assert run.status == "FAILED"
        assert run.error_summary["error_type"] == "IntegrityError"
    finally:
        db.close()
