from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import GateEvaluation, Page, ProcessingRun, SourceBlock


def evaluate_g1_document_representation(db: Session, run_id: str) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")

    pages = (
        db.query(Page)
        .filter(Page.document_version_id == run.document_version_id)
        .order_by(Page.page_number)
        .all()
    )
    blocks = (
        db.query(SourceBlock)
        .filter(SourceBlock.processing_run_id == run.id)
        .all()
    )

    page_ids_with_blocks = {block.page_id for block in blocks if block.raw_text}
    represented_pages = sum(1 for page in pages if page.id in page_ids_with_blocks)
    coverage = represented_pages / len(pages) if pages else 0.0
    invalid_geometry = sum(
        1
        for block in blocks
        if not _valid_bbox(block.bbox)
    )

    metrics = {
        "page_count": len(pages),
        "represented_pages": represented_pages,
        "text_block_count": len(blocks),
        "page_representation_coverage": coverage,
        "invalid_geometry_blocks": invalid_geometry,
        "silent_page_loss": max(len(pages) - represented_pages, 0),
    }
    blocking = []
    if not blocks:
        blocking.append("no_source_blocks")
    if invalid_geometry:
        blocking.append("invalid_geometry")
    if represented_pages != len(pages):
        blocking.append("silent_page_loss")

    status = "PASS" if not blocking else "FAIL"
    existing = (
        db.query(GateEvaluation)
        .filter(
            GateEvaluation.processing_run_id == run.id,
            GateEvaluation.gate == "G1",
        )
        .one_or_none()
    )
    if existing is None:
        existing = GateEvaluation(
            processing_run_id=run.id,
            gate="G1",
            ruleset_version="1.0.0",
            scope_type="DOCUMENT",
            scope_id=run.document_version_id,
            status=status,
            metrics=metrics,
            blocking_failures=blocking,
            evidence={"source_block_count": len(blocks)},
        )
        db.add(existing)
    else:
        existing.status = status
        existing.metrics = metrics
        existing.blocking_failures = blocking
        existing.evidence = {"source_block_count": len(blocks)}

    db.commit()
    return {
        "gate": "G1",
        "status": status,
        "metrics": metrics,
        "blocking_failures": blocking,
    }


def _valid_bbox(bbox: dict) -> bool:
    try:
        if bbox.get("unit") != "normalized":
            return False
        x1 = float(bbox["x1"])
        y1 = float(bbox["y1"])
        x2 = float(bbox["x2"])
        y2 = float(bbox["y2"])
    except (KeyError, TypeError, ValueError):
        return False
    return 0.0 <= x1 <= x2 <= 1.0 and 0.0 <= y1 <= y2 <= 1.0
