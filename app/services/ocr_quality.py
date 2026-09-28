from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ReviewTask, SourceBlock

OPEN_STATUSES = ["OPEN", "IN_PROGRESS", "ESCALATED"]


def route_ocr_quality_reviews(
    db: Session,
    run_id: str,
    *,
    min_confidence: float = 0.85,
) -> dict:
    blocks = (
        db.query(SourceBlock)
        .filter(
            SourceBlock.processing_run_id == run_id,
            SourceBlock.source_engine.like("ocr:%"),
        )
        .all()
    )
    low = [
        block
        for block in blocks
        if block.confidence is None or float(block.confidence) < min_confidence
    ]

    for block in low:
        existing = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.processing_run_id == run_id,
                ReviewTask.target_entity_type == "SourceBlock",
                ReviewTask.target_entity_id == block.id,
                ReviewTask.reason_code == "LOW_OCR_CONFIDENCE",
                ReviewTask.status.in_(OPEN_STATUSES),
            )
            .first()
        )
        if existing is None:
            db.add(
                ReviewTask(
                    processing_run_id=run_id,
                    reason_code="LOW_OCR_CONFIDENCE",
                    status="OPEN",
                    target_entity_type="SourceBlock",
                    target_entity_id=block.id,
                    target_field_path="raw_text",
                    source_context={
                        "raw_text": block.raw_text,
                        "confidence": block.confidence,
                        "bbox": block.bbox,
                        "page_id": block.page_id,
                        "source_engine": block.source_engine,
                        "source_engine_version": block.source_engine_version,
                        "min_confidence": min_confidence,
                    },
                    candidate_values=[],
                )
            )

    db.commit()
    return {
        "run_id": run_id,
        "ocr_blocks": len(blocks),
        "low_confidence_blocks": len(low),
        "min_confidence": min_confidence,
    }
