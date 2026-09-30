from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Page, ProcessingRun, ReviewTask


def route_no_text_page_reviews(
    db: Session,
    run_id: str,
    *,
    page_numbers: set[int],
) -> dict:
    """Route pages without a text layer to review instead of silently accepting them."""
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    pages = (
        db.query(Page)
        .filter(
            Page.document_version_id == run.document_version_id,
            Page.page_number.in_(page_numbers),
        )
        .order_by(Page.page_number)
        .all()
    )
    if {page.page_number for page in pages} != page_numbers:
        raise ValueError("no-text review pages do not match persisted document pages")

    created = 0
    for page in pages:
        existing = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.processing_run_id == run_id,
                ReviewTask.reason_code == "NO_TEXT_LAYER",
                ReviewTask.target_entity_type == "Page",
                ReviewTask.target_entity_id == page.id,
            )
            .one_or_none()
        )
        if existing is not None:
            continue
        db.add(
            ReviewTask(
                processing_run_id=run_id,
                reason_code="NO_TEXT_LAYER",
                status="OPEN",
                target_entity_type="Page",
                target_entity_id=page.id,
                target_field_path="content_classification",
                source_context={
                    "page_number": page.page_number,
                    "render_artifact_id": page.render_artifact_id,
                    "reason": "native text layer has fewer than the configured minimum characters",
                },
                candidate_values=["RUN_OCR", "CONFIRM_NON_TEXT_PAGE"],
            )
        )
        created += 1
    db.commit()
    return {
        "run_id": run_id,
        "review_reason": "NO_TEXT_LAYER",
        "page_numbers": sorted(page_numbers),
        "created_review_tasks": created,
    }
