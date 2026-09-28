from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.adapters.ocr_base import OcrEngineAdapter, OcrPageInput
from app.models import Artifact, Page, ProcessingRun, SourceBlock


def extract_ocr_blocks(
    db: Session,
    run_id: str,
    adapter: OcrEngineAdapter,
    *,
    page_numbers: set[int] | None = None,
) -> dict:
    """Run OCR on selected rendered pages and persist engine-neutral SourceBlocks."""
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")

    pages = (
        db.query(Page)
        .filter(Page.document_version_id == run.document_version_id)
        .order_by(Page.page_number)
        .all()
    )
    if page_numbers is not None:
        pages = [page for page in pages if page.page_number in page_numbers]
    if not pages:
        raise ValueError("processing run has no rendered pages selected for OCR")

    selected_page_ids = [page.id for page in pages]
    db.query(SourceBlock).filter(
        SourceBlock.processing_run_id == run_id,
        SourceBlock.page_id.in_(selected_page_ids),
        SourceBlock.source_engine.like("ocr:%"),
    ).delete(synchronize_session=False)

    block_count = 0
    page_count = 0
    confidences: list[float] = []

    for page in pages:
        artifact = db.get(Artifact, page.render_artifact_id)
        if artifact is None:
            raise ValueError(f"page {page.page_number} has no render artifact")
        image_path = Path(artifact.object_key)
        if not image_path.is_file():
            raise ValueError(f"page {page.page_number} render artifact is unavailable")

        result = adapter.extract_page(
            OcrPageInput(
                page_number=page.page_number,
                image_bytes=image_path.read_bytes(),
                mime_type=artifact.mime_type or "image/png",
            )
        )
        if result.page_number != page.page_number:
            raise ValueError("OCR adapter returned mismatched page number")

        page_count += 1
        for block in sorted(result.blocks, key=lambda item: item.reading_order):
            text = block.text.strip()
            if not text:
                continue
            db.add(
                SourceBlock(
                    page_id=page.id,
                    processing_run_id=run_id,
                    block_type=block.block_type,
                    reading_order=block.reading_order,
                    raw_text=text,
                    confidence=block.confidence,
                    bbox=block.bbox.as_dict(),
                    source_engine=f"ocr:{result.engine_name}",
                    source_engine_version=result.engine_version,
                    metadata_json={
                        **block.metadata,
                        "ocr_result_metadata": result.metadata,
                    },
                )
            )
            block_count += 1
            if block.confidence is not None:
                confidences.append(block.confidence)

    mean_confidence = sum(confidences) / len(confidences) if confidences else None
    run.metrics = {
        **(run.metrics or {}),
        "ocr_engine": adapter.name,
        "ocr_engine_version": adapter.version,
        "ocr_pages": page_count,
        "ocr_blocks": block_count,
        "ocr_mean_confidence": mean_confidence,
    }
    db.commit()
    return {
        "run_id": run_id,
        "engine": adapter.name,
        "engine_version": adapter.version,
        "page_count": page_count,
        "page_numbers": [page.page_number for page in pages],
        "block_count": block_count,
        "mean_confidence": mean_confidence,
    }
