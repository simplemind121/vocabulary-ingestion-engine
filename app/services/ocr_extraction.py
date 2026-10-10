from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy.orm import Session

from app.adapters.ocr_base import OcrEngineAdapter, OcrPageInput
from app.models import Artifact, DocumentVersion, Page, ProcessingRun, SourceBlock


def extract_ocr_blocks(
    db: Session,
    run_id: str,
    adapter: OcrEngineAdapter,
    *,
    page_numbers: set[int] | None = None,
    page_workers: int = 1,
    adapter_factory: Callable[[], OcrEngineAdapter] | None = None,
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
    selected_page_numbers = [page.page_number for page in pages]
    source_engine = f"ocr:{adapter.name}"
    existing_blocks = (
        db.query(SourceBlock)
        .filter(
            SourceBlock.processing_run_id == run_id,
            SourceBlock.page_id.in_(selected_page_ids),
            SourceBlock.source_engine.like("ocr:%"),
        )
        .all()
    )
    matching_blocks = [
        block
        for block in existing_blocks
        if block.source_engine == source_engine
        and block.source_engine_version == adapter.version
    ]
    metrics = dict(run.metrics or {})
    recorded_pages = metrics.get("ocr_page_numbers")
    selection_matches = recorded_pages == selected_page_numbers
    if recorded_pages is None and matching_blocks:
        selection_matches = {block.page_id for block in matching_blocks} == set(
            selected_page_ids
        )
    if (
        selection_matches
        and metrics.get("ocr_engine") == adapter.name
        and metrics.get("ocr_engine_version") == adapter.version
    ):
        confidences = [
            float(block.confidence)
            for block in matching_blocks
            if block.confidence is not None
        ]
        mean_confidence = (
            sum(confidences) / len(confidences) if confidences else None
        )
        return {
            "run_id": run_id,
            "engine": adapter.name,
            "engine_version": adapter.version,
            "page_count": len(pages),
            "page_numbers": selected_page_numbers,
            "block_count": len(matching_blocks),
            "mean_confidence": mean_confidence,
            "reused": True,
        }

    progress = metrics.get("ocr_progress") or {}
    resumable = (
        progress.get("engine") == adapter.name
        and progress.get("engine_version") == adapter.version
        and progress.get("page_numbers") == selected_page_numbers
    )
    done: set[int] = set(progress.get("done") or []) if resumable else set()
    if not resumable:
        if any(
            (block.metadata_json or {}).get("human_ocr_review") for block in existing_blocks
        ):
            raise ValueError("cannot replace human-reviewed OCR blocks")
        db.query(SourceBlock).filter(
            SourceBlock.processing_run_id == run_id,
            SourceBlock.page_id.in_(selected_page_ids),
            SourceBlock.source_engine.like("ocr:%"),
        ).delete(synchronize_session=False)
        db.commit()

    version = db.get(DocumentVersion, run.document_version_id)
    document_sha256 = version.sha256 if version is not None else None

    def page_input(page: Page) -> OcrPageInput:
        artifact = db.get(Artifact, page.render_artifact_id)
        if artifact is None:
            raise ValueError(f"page {page.page_number} has no render artifact")
        image_path = Path(artifact.object_key)
        if not image_path.is_file():
            raise ValueError(f"page {page.page_number} render artifact is unavailable")
        return OcrPageInput(
            page_number=page.page_number,
            image_bytes=image_path.read_bytes(),
            mime_type=artifact.mime_type or "image/png",
            document_sha256=document_sha256,
        )

    pending = [page for page in pages if page.page_number not in done]
    workers = max(1, min(page_workers, len(pending) or 1))
    local = threading.local()
    local.adapter = adapter

    def read(page_input_: OcrPageInput):
        if getattr(local, "adapter", None) is None:
            # Each extra thread owns its engines; they are not shared.
            local.adapter = adapter_factory()
        return local.adapter.extract_page(page_input_)

    if workers > 1 and adapter_factory is None:
        workers = 1

    def results():
        if workers == 1:
            for page in pending:
                yield page, adapter.extract_page(page_input(page))
            return
        with ThreadPoolExecutor(max_workers=workers) as pool:
            window: list = []
            for page in pending:
                window.append((page, pool.submit(read, page_input(page))))
                if len(window) >= workers * 2:
                    first_page, future = window.pop(0)
                    yield first_page, future.result()
            for first_page, future in window:
                yield first_page, future.result()

    # Every page is committed as soon as it is read, so progress is visible
    # and an interrupted run picks up at the next unread page.
    for page, result in results():
        if result.page_number != page.page_number:
            raise ValueError("OCR adapter returned mismatched page number")
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
        done.add(page.page_number)
        run.metrics = {
            **(run.metrics or {}),
            "ocr_progress": {
                "engine": adapter.name,
                "engine_version": adapter.version,
                "page_numbers": selected_page_numbers,
                "done": sorted(done),
                "total": len(pages),
            },
        }
        db.commit()

    stored = (
        db.query(SourceBlock)
        .filter(
            SourceBlock.processing_run_id == run_id,
            SourceBlock.page_id.in_(selected_page_ids),
            SourceBlock.source_engine.like("ocr:%"),
        )
        .all()
    )
    block_count = len(stored)
    page_count = len(pages)
    confidences = [float(block.confidence) for block in stored if block.confidence is not None]

    mean_confidence = sum(confidences) / len(confidences) if confidences else None
    run.metrics = {
        **(run.metrics or {}),
        "ocr_engine": adapter.name,
        "ocr_engine_version": adapter.version,
        "ocr_pages": page_count,
        "ocr_page_numbers": selected_page_numbers,
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
        "reused": False,
    }
