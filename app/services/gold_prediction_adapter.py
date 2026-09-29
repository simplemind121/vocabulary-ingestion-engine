from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Artifact, DocumentVersion, Page, ProcessingRun, SourceBlock
from app.services.gold_prediction_contract import build_gold_prediction


def build_gold_prediction_from_run(
    db: Session,
    run_id: str,
    scaffold: dict[str, Any],
) -> dict[str, Any]:
    """Build a source-grounded Gold DRAFT prediction from persisted extraction output.

    The adapter is deliberately limited to SourceBlock transport in this slice.
    Entry segmentation and canonical vocabulary remain empty until their persisted
    outputs are joined through equally strict provenance contracts.
    """
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("gold_prediction_processing_run_not_found")

    version = db.get(DocumentVersion, run.document_version_id)
    if version is None:
        raise ValueError("gold_prediction_document_version_not_found")
    if scaffold.get("document_sha256") != version.sha256:
        raise ValueError("gold_prediction_document_sha256_mismatch")

    page_number = scaffold.get("page_number")
    page = (
        db.query(Page)
        .filter(
            Page.document_version_id == version.id,
            Page.page_number == page_number,
        )
        .one_or_none()
    )
    if page is None:
        raise ValueError("gold_prediction_page_not_found")

    render = db.get(Artifact, page.render_artifact_id)
    if render is None or render.sha256 is None:
        raise ValueError("gold_prediction_render_artifact_missing")
    if scaffold.get("page_image_sha256") != render.sha256:
        raise ValueError("gold_prediction_page_image_sha256_mismatch")

    rows = (
        db.query(SourceBlock)
        .filter(
            SourceBlock.processing_run_id == run.id,
            SourceBlock.page_id == page.id,
        )
        .order_by(SourceBlock.reading_order, SourceBlock.id)
        .all()
    )
    blocks = [
        {
            "source_block_id": row.id,
            "block_type": row.block_type,
            "reading_order": row.reading_order,
            "raw_text": row.raw_text,
            "confidence": row.confidence,
            "bbox": dict(row.bbox),
            "source_engine": row.source_engine,
            "source_engine_version": row.source_engine_version,
            "metadata": dict(row.metadata_json or {}),
        }
        for row in rows
    ]

    return build_gold_prediction(
        scaffold,
        blocks=blocks,
        entries=[],
        vocabulary=[],
    )
