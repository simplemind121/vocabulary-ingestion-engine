import fitz

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.db import SessionLocal
from app.idr import BoundingBox, TextBlock
from app.models import ReviewTask
from app.services.pipeline import run_pipeline
from app.services.review import resolve_review_task


class LowConfidenceOcr:
    name = "low-confidence"
    version = "1"

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        return OcrPageResult(
            page_number=page.page_number,
            blocks=[
                TextBlock(
                    text="medication* [medication] n. medicine",
                    bbox=BoundingBox(0.1, 0.1, 0.9, 0.2),
                    reading_order=0,
                    confidence=0.42,
                )
            ],
            engine_name=self.name,
            engine_version=self.version,
        )


def test_low_confidence_ocr_routes_to_g1_review(client):
    doc = fitz.open()
    doc.new_page()
    payload = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/documents",
        files={"file": ("low-confidence.pdf", payload, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        result = run_pipeline(
            db,
            run_id,
            publish=False,
            ocr_adapter=LowConfidenceOcr(),
            ocr_min_confidence=0.85,
        )
        tasks = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.processing_run_id == run_id,
                ReviewTask.reason_code == "LOW_OCR_CONFIDENCE",
            )
            .all()
        )
    finally:
        db.close()

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["blocked_gate"] == "G1"
    assert len(tasks) == 1
    assert tasks[0].target_entity_type == "SourceBlock"
    assert tasks[0].target_field_path == "raw_text"
    assert tasks[0].source_context["confidence"] == 0.42
    assert tasks[0].source_context["min_confidence"] == 0.85


def test_human_accepted_low_confidence_ocr_does_not_reopen_on_retry(client):
    doc = fitz.open()
    doc.new_page()
    payload = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/documents",
        files={"file": ("reviewed-low-confidence.pdf", payload, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        first = run_pipeline(
            db,
            run_id,
            publish=False,
            ocr_adapter=LowConfidenceOcr(),
            ocr_min_confidence=0.85,
        )
        task = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.processing_run_id == run_id,
                ReviewTask.reason_code == "LOW_OCR_CONFIDENCE",
            )
            .one()
        )
        resolve_review_task(
            db,
            task.id,
            resolution={"decision": "ACCEPT"},
            reviewer_id="human-1",
        )

        second = run_pipeline(
            db,
            run_id,
            publish=False,
            ocr_adapter=LowConfidenceOcr(),
            ocr_min_confidence=0.85,
        )
        open_tasks = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.processing_run_id == run_id,
                ReviewTask.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"]),
            )
            .count()
        )
    finally:
        db.close()

    assert first["status"] == "REVIEW_REQUIRED"
    assert second["status"] == "COMPLETED"
    assert open_tasks == 0
