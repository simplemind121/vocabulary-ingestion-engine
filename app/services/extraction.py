from __future__ import annotations

import fitz
from sqlalchemy.orm import Session

from app.adapters.pdf_native import PyMuPDFNativeAdapter
from app.models import (
    Artifact,
    DocumentVersion,
    Page,
    ProcessingRun,
    ProcessingStep,
    SourceBlock,
    SourceEntry,
)


def extract_native_blocks(
    db: Session,
    run_id: str,
    *,
    page_numbers: set[int] | None = None,
) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    version = db.get(DocumentVersion, run.document_version_id)
    if version is None:
        raise ValueError("document version not found")
    artifact = db.get(Artifact, version.source_artifact_id)
    if artifact is None:
        raise ValueError("source artifact not found")

    pages = (
        db.query(Page)
        .filter(Page.document_version_id == version.id)
        .order_by(Page.page_number)
        .all()
    )
    if page_numbers is not None:
        pages = [page for page in pages if page.page_number in page_numbers]
    if not pages:
        raise ValueError("processing run has no rendered pages selected for native extraction")
    pages_by_number = {page.page_number: page for page in pages}

    selected_page_ids = [page.id for page in pages]
    existing = db.query(SourceBlock).filter(
        SourceBlock.processing_run_id == run.id,
        SourceBlock.page_id.in_(selected_page_ids),
        SourceBlock.source_engine == PyMuPDFNativeAdapter.name,
    ).count()
    segmented = (
        db.query(SourceEntry).filter(SourceEntry.processing_run_id == run.id).first() is not None
    )
    if existing and (page_numbers is None or segmented):
        # Once entries reference these blocks they are immutable evidence: a
        # resumed run must reuse them, never delete and re-extract them.
        return {"run_id": run.id, "source_blocks": existing, "reused": True}

    if page_numbers is not None:
        db.query(SourceBlock).filter(
            SourceBlock.processing_run_id == run.id,
            SourceBlock.page_id.in_(selected_page_ids),
            SourceBlock.source_engine == PyMuPDFNativeAdapter.name,
        ).delete(synchronize_session=False)

    step = (
        db.query(ProcessingStep)
        .filter(ProcessingStep.processing_run_id == run.id, ProcessingStep.sequence_no == 10)
        .one_or_none()
    )
    if step is None:
        step = ProcessingStep(
            processing_run_id=run.id,
            step_type="NATIVE_TEXT_EXTRACTION",
            sequence_no=10,
            processor_name=PyMuPDFNativeAdapter.name,
            processor_version=str(PyMuPDFNativeAdapter.version),
            configuration={"page_numbers": sorted(page_numbers) if page_numbers else None},
            status="RUNNING",
        )
        db.add(step)
    else:
        step.status = "RUNNING"
        step.retry_count += 1
        step.error = None
    db.flush()

    adapter = PyMuPDFNativeAdapter()
    block_count = 0
    pdf = fitz.open(artifact.object_key)
    try:
        for page_index, pdf_page in enumerate(pdf, start=1):
            if page_index not in pages_by_number:
                continue
            page_row = pages_by_number[page_index]
            for block in adapter.extract_page(pdf_page):
                db.add(
                    SourceBlock(
                        page_id=page_row.id,
                        processing_run_id=run.id,
                        block_type=block.block_type,
                        reading_order=block.reading_order,
                        raw_text=block.text,
                        confidence=block.confidence,
                        bbox=block.bbox.as_dict(),
                        source_engine=adapter.name,
                        source_engine_version=str(adapter.version),
                        metadata_json=block.metadata,
                    )
                )
                block_count += 1
    except Exception:
        db.rollback()
        raise
    finally:
        pdf.close()

    step.status = "COMPLETED"
    step.metrics = {
        "source_blocks": block_count,
        "idempotent_reuse": False,
        "page_numbers": sorted(pages_by_number),
    }
    db.commit()
    return {
        "run_id": run.id,
        "source_blocks": block_count,
        "page_numbers": sorted(pages_by_number),
        "reused": False,
    }
