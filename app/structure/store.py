"""Saving and reading a run's structured pages."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Artifact, DocumentVersion, Page, ProcessingRun, StructuredPage
from app.structure.evidence import run_lines, text_layer_words
from app.structure.plan import compile_plan

ACCEPTED = "ACCEPTED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"


def source_pdf(db: Session, run_id: str) -> str | None:
    run = db.get(ProcessingRun, run_id)
    version = db.get(DocumentVersion, run.document_version_id) if run is not None else None
    source = db.get(Artifact, version.source_artifact_id) if version is not None else None
    return source.object_key if source is not None and Path(source.object_key).is_file() else None


def save_page(
    db: Session,
    run_id: str,
    tree: dict,
    *,
    producer: str,
    author: str | None = None,
    source_plan: str | None = None,
) -> StructuredPage:
    """Store ``tree`` (a page dict with ``page``, ``kind``, ``blocks`` and ``checked``) as the page's next version.

    A tree with invented words or dropped lines is kept, but as REVIEW_REQUIRED.
    """
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    number = int(tree["page"])
    page = (
        db.query(Page)
        .filter(Page.document_version_id == run.document_version_id, Page.page_number == number)
        .one_or_none()
    )
    if page is None:
        raise ValueError(f"page {number} is not in this run's document")
    checks = tree.get("checked") or {}
    clean = not checks.get("invented") and not checks.get("dropped_lines") and "invented" in checks
    last = (
        db.query(func.max(StructuredPage.version))
        .filter(StructuredPage.processing_run_id == run_id, StructuredPage.page_id == page.id)
        .scalar()
    )
    record = StructuredPage(
        processing_run_id=run_id,
        page_id=page.id,
        page_number=number,
        version=(last or 0) + 1,
        kind=tree.get("kind") or "other",
        unit=tree.get("unit"),
        title=tree.get("title"),
        blocks=tree["blocks"],
        checks=checks,
        producer=producer,
        author=author or checks.get("by"),
        source_plan=source_plan,
        status=ACCEPTED if clean else REVIEW_REQUIRED,
    )
    db.add(record)
    db.commit()
    return record


def compile_and_save(db: Session, run_id: str, number: int, plan: str, *, author: str) -> StructuredPage:
    """Compile a page plan against the run's own evidence and store it."""
    lines = run_lines(db, run_id).get(number, [])
    pdf = source_pdf(db, run_id)
    layer = text_layer_words(pdf, number) if pdf else []
    tree = compile_plan(number, plan, lines, layer, by=author)
    return save_page(db, run_id, tree, producer="page-plan", author=author, source_plan=plan)


def current_pages(db: Session, run_id: str) -> dict[int, StructuredPage]:
    """The latest version of every structured page of the run."""
    latest: dict[int, StructuredPage] = {}
    for record in (
        db.query(StructuredPage)
        .filter(StructuredPage.processing_run_id == run_id)
        .order_by(StructuredPage.page_number, StructuredPage.version)
    ):
        latest[record.page_number] = record
    return latest


def as_tree(record: StructuredPage) -> dict:
    """A stored page in the same shape a page plan compiles to."""
    return {
        "page": record.page_number,
        "kind": record.kind,
        "unit": record.unit,
        "title": record.title,
        "blocks": record.blocks,
        "checked": record.checks,
    }
