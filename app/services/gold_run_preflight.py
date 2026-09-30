from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Artifact,
    DocumentVersion,
    Page,
    ProcessingRun,
    SourceBlock,
    SourceEntry,
    VocabularyEntry,
)


def inspect_gold_run_candidates(
    db: Session,
    *,
    document_sha256: str,
    page_numbers: list[int],
    page_image_sha256: dict[int, str],
) -> list[dict[str, Any]]:
    """Report persisted runs that can be evaluated for the frozen Gold sample.

    This is deliberately read-only. It never guesses a run ID and never upgrades a
    candidate to "ready" unless document identity, all frozen page renders, and
    persisted block/entry/vocabulary layers are present.
    """
    versions = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.sha256 == document_sha256)
        .order_by(DocumentVersion.created_at.desc(), DocumentVersion.id)
        .all()
    )
    results: list[dict[str, Any]] = []
    for version in versions:
        runs = (
            db.query(ProcessingRun)
            .filter(ProcessingRun.document_version_id == version.id)
            .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id)
            .all()
        )
        pages = (
            db.query(Page)
            .filter(
                Page.document_version_id == version.id,
                Page.page_number.in_(page_numbers),
            )
            .all()
        )
        pages_by_number = {page.page_number: page for page in pages}
        render_mismatches: list[int] = []
        missing_pages: list[int] = []
        for page_number in page_numbers:
            page = pages_by_number.get(page_number)
            if page is None:
                missing_pages.append(page_number)
                continue
            artifact = db.get(Artifact, page.render_artifact_id)
            expected = page_image_sha256.get(page_number)
            if artifact is None or artifact.sha256 != expected:
                render_mismatches.append(page_number)

        for run in runs:
            block_count = (
                db.query(func.count(SourceBlock.id))
                .filter(SourceBlock.processing_run_id == run.id)
                .scalar()
                or 0
            )
            entry_count = (
                db.query(func.count(SourceEntry.id))
                .filter(SourceEntry.processing_run_id == run.id)
                .scalar()
                or 0
            )
            vocabulary_count = (
                db.query(func.count(VocabularyEntry.id))
                .filter(VocabularyEntry.processing_run_id == run.id)
                .scalar()
                or 0
            )
            frozen_page_ids = [page.id for page in pages]
            covered_pages = 0
            if frozen_page_ids:
                covered_pages = (
                    db.query(func.count(func.distinct(SourceBlock.page_id)))
                    .filter(
                        SourceBlock.processing_run_id == run.id,
                        SourceBlock.page_id.in_(frozen_page_ids),
                    )
                    .scalar()
                    or 0
                )
            blockers: list[str] = []
            if missing_pages:
                blockers.append("FROZEN_PAGES_MISSING")
            if render_mismatches:
                blockers.append("FROZEN_RENDER_SHA256_MISMATCH")
            if covered_pages != len(page_numbers):
                blockers.append("FROZEN_PAGES_WITHOUT_SOURCE_BLOCKS")
            if entry_count == 0:
                blockers.append("SOURCE_ENTRIES_MISSING")
            if vocabulary_count == 0:
                blockers.append("VOCABULARY_ENTRIES_MISSING")
            results.append(
                {
                    "processing_run_id": run.id,
                    "document_version_id": version.id,
                    "run_status": run.status,
                    "pipeline_version": run.pipeline_version,
                    "canonical_schema_version": run.canonical_schema_version,
                    "frozen_page_count": len(page_numbers),
                    "frozen_pages_with_blocks": covered_pages,
                    "source_block_count": block_count,
                    "source_entry_count": entry_count,
                    "vocabulary_entry_count": vocabulary_count,
                    "missing_pages": sorted(missing_pages),
                    "render_sha256_mismatches": sorted(render_mismatches),
                    "blockers": blockers,
                    "ready_for_gold_draft": not blockers,
                }
            )
    return results
