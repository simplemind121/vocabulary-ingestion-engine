from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ReviewTask, SourceBlock

OPEN_STATUSES = ["OPEN", "IN_PROGRESS", "ESCALATED"]
# Lines the independent readers could not confirm. They do not stop the run:
# they are parked for arbitration and keep their entries out of Gold meanwhile.
DEFERRED = "DEFERRED"
READERS_DISAGREE = "OCR_READERS_DISAGREE"
_UNCONFIRMED = {"DISPUTED", "SINGLE_READER"}
_CONFIRMED = {"UNANIMOUS", "MAJORITY"}
_FURNITURE = {"HEADWORD_CHECKLIST", "RUNNING_HEADER", "NON_ENTRY_PAGE"}


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
    pending = [
        block
        for block in blocks
        if (block.metadata_json or {}).get("human_ocr_review", {}).get("decision")
        not in {"ACCEPT", "DISCARD"}
        and (block.metadata_json or {}).get("role") not in _FURNITURE
        and not (block.raw_text or "").strip().isdigit()
    ]
    unconfirmed = [
        block
        for block in pending
        if ((block.metadata_json or {}).get("consensus") or {}).get("status") in _UNCONFIRMED
    ]
    deferred_ids = {block.id for block in unconfirmed}
    low = [
        block
        for block in pending
        if block.id not in deferred_ids
        # A line two independent readers agree on is confirmed whatever score
        # the primary engine gave it.
        and ((block.metadata_json or {}).get("consensus") or {}).get("status") not in _CONFIRMED
        and (block.confidence is None or float(block.confidence) < min_confidence)
    ]
    for block in unconfirmed:
        consensus = block.metadata_json["consensus"]
        known = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.processing_run_id == run_id,
                ReviewTask.target_entity_type == "SourceBlock",
                ReviewTask.target_entity_id == block.id,
                ReviewTask.reason_code == READERS_DISAGREE,
            )
            .first()
        )
        if known is None:
            db.add(
                ReviewTask(
                    processing_run_id=run_id,
                    reason_code=READERS_DISAGREE,
                    status=DEFERRED,
                    target_entity_type="SourceBlock",
                    target_entity_id=block.id,
                    target_field_path="raw_text",
                    source_context={
                        "raw_text": block.raw_text,
                        "consensus_status": consensus.get("status"),
                        "disputes": consensus.get("disputes"),
                        "other_readings": consensus.get("other_readings"),
                        "page_id": block.page_id,
                    },
                    candidate_values=[],
                )
            )

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
        "unconfirmed_blocks_deferred": len(unconfirmed),
        "min_confidence": min_confidence,
    }
