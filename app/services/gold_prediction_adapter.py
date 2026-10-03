from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    Artifact,
    DocumentVersion,
    Page,
    ProcessingRun,
    SourceBlock,
    SourceEntry,
    SourceEntryBlock,
    VocabularyEntry,
)
from app.services.gold_prediction_contract import build_gold_prediction


def build_gold_prediction_from_run(
    db: Session,
    run_id: str,
    scaffold: dict[str, Any],
) -> dict[str, Any]:
    """Build a source-grounded Gold DRAFT prediction from persisted pipeline output.

    Blocks, segmented source entries, and canonical vocabulary are transported only
    when they belong to the same ProcessingRun and are provenance-linked to the
    frozen page. Cross-page entries remain visible through their complete ordered
    source_block_ids, while page membership is established by at least one linked
    block on the frozen page.
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

    entry_rows = (
        db.query(SourceEntry)
        .join(SourceEntryBlock, SourceEntryBlock.source_entry_id == SourceEntry.id)
        .join(SourceBlock, SourceBlock.id == SourceEntryBlock.source_block_id)
        .filter(
            SourceEntry.processing_run_id == run.id,
            SourceEntry.document_version_id == version.id,
            SourceBlock.processing_run_id == run.id,
            SourceBlock.page_id == page.id,
        )
        .order_by(SourceEntry.entry_order, SourceEntry.id)
        .distinct()
        .all()
    )
    entries = []
    for entry in entry_rows:
        links = (
            db.query(SourceEntryBlock)
            .join(SourceBlock, SourceBlock.id == SourceEntryBlock.source_block_id)
            .filter(
                SourceEntryBlock.source_entry_id == entry.id,
                SourceBlock.processing_run_id == run.id,
            )
            .order_by(SourceEntryBlock.block_order, SourceEntryBlock.source_block_id)
            .all()
        )
        entries.append(
            {
                "source_entry_id": entry.id,
                "entry_order": entry.entry_order,
                "raw_text": entry.raw_text,
                "segmentation_confidence": entry.segmentation_confidence,
                "continuation_type": entry.continuation_type,
                "status": entry.status,
                "source_block_ids": [link.source_block_id for link in links],
                "metadata": dict(entry.metadata_json or {}),
            }
        )

    entry_ids = [entry.id for entry in entry_rows]
    vocabulary_rows = []
    if entry_ids:
        vocabulary_rows = (
            db.query(VocabularyEntry)
            .filter(
                VocabularyEntry.processing_run_id == run.id,
                VocabularyEntry.source_entry_id.in_(entry_ids),
            )
            .order_by(VocabularyEntry.source_entry_id, VocabularyEntry.id)
            .all()
        )
    vocabulary = [
        {
            "vocabulary_entry_id": row.id,
            "source_entry_id": row.source_entry_id,
            "lemma": row.lemma,
            "display_form": row.display_form,
            "language": row.language,
            "verification_status": row.verification_status,
            "canonical_schema_version": row.canonical_schema_version,
            "metadata": dict(row.metadata_json or {}),
        }
        for row in vocabulary_rows
    ]

    return build_gold_prediction(
        scaffold,
        blocks=blocks,
        entries=entries,
        vocabulary=vocabulary,
    )
