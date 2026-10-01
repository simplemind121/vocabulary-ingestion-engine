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
    SourceEntryBlock,
    VocabularyEntry,
)


def inspect_gold_run_candidates(
    db: Session,
    *,
    document_sha256: str,
    page_numbers: list[int],
    page_image_sha256: dict[int, str],
    entry_page_numbers: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Report persisted runs that can be evaluated for the frozen Gold sample.

    This is deliberately read-only. It never guesses a run ID and never upgrades a
    candidate to "ready" unless document identity, all frozen page renders, and
    page-bound block/entry/vocabulary layers are present.
    """
    required_entry_page_numbers = set(
        page_numbers if entry_page_numbers is None else entry_page_numbers
    )
    unexpected_entry_pages = required_entry_page_numbers - set(page_numbers)
    if unexpected_entry_pages:
        raise ValueError(
            "entry_page_numbers_must_be_subset_of_page_numbers: "
            + ",".join(str(page) for page in sorted(unexpected_entry_pages))
        )

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
            block_pages: set[str] = set()
            entry_pages: set[str] = set()
            vocabulary_pages: set[str] = set()
            if frozen_page_ids:
                block_pages = {
                    page_id
                    for (page_id,) in (
                        db.query(SourceBlock.page_id)
                        .filter(
                            SourceBlock.processing_run_id == run.id,
                            SourceBlock.page_id.in_(frozen_page_ids),
                        )
                        .distinct()
                        .all()
                    )
                }
                entry_pages = {
                    page_id
                    for (page_id,) in (
                        db.query(SourceBlock.page_id)
                        .join(
                            SourceEntryBlock,
                            SourceEntryBlock.source_block_id == SourceBlock.id,
                        )
                        .join(
                            SourceEntry,
                            SourceEntry.id == SourceEntryBlock.source_entry_id,
                        )
                        .filter(
                            SourceBlock.processing_run_id == run.id,
                            SourceEntry.processing_run_id == run.id,
                            SourceBlock.page_id.in_(frozen_page_ids),
                        )
                        .distinct()
                        .all()
                    )
                }
                vocabulary_pages = {
                    page_id
                    for (page_id,) in (
                        db.query(SourceBlock.page_id)
                        .join(
                            SourceEntryBlock,
                            SourceEntryBlock.source_block_id == SourceBlock.id,
                        )
                        .join(
                            SourceEntry,
                            SourceEntry.id == SourceEntryBlock.source_entry_id,
                        )
                        .join(
                            VocabularyEntry,
                            VocabularyEntry.source_entry_id == SourceEntry.id,
                        )
                        .filter(
                            SourceBlock.processing_run_id == run.id,
                            SourceEntry.processing_run_id == run.id,
                            VocabularyEntry.processing_run_id == run.id,
                            SourceBlock.page_id.in_(frozen_page_ids),
                        )
                        .distinct()
                        .all()
                    )
                }
            page_number_by_id = {page.id: page.page_number for page in pages}
            required_entry_page_ids = {
                page.id
                for page in pages
                if page.page_number in required_entry_page_numbers
            }
            missing_entry_pages = required_entry_page_numbers - set(pages_by_number)
            pages_without_blocks = sorted(
                page_number_by_id[page_id]
                for page_id in frozen_page_ids
                if page_id not in block_pages
            )
            pages_without_entries = sorted(
                page_number_by_id[page_id]
                for page_id in required_entry_page_ids
                if page_id not in entry_pages
            )
            pages_without_vocabulary = sorted(
                page_number_by_id[page_id]
                for page_id in required_entry_page_ids
                if page_id not in vocabulary_pages
            )
            blockers: list[str] = []
            if missing_pages:
                blockers.append("FROZEN_PAGES_MISSING")
            if render_mismatches:
                blockers.append("FROZEN_RENDER_SHA256_MISMATCH")
            if pages_without_blocks or missing_pages:
                blockers.append("FROZEN_PAGES_WITHOUT_SOURCE_BLOCKS")
            if pages_without_entries or missing_entry_pages:
                blockers.append("FROZEN_PAGES_WITHOUT_SOURCE_ENTRIES")
            if pages_without_vocabulary or missing_entry_pages:
                blockers.append("FROZEN_PAGES_WITHOUT_VOCABULARY_ENTRIES")
            results.append(
                {
                    "processing_run_id": run.id,
                    "document_version_id": version.id,
                    "run_status": run.status,
                    "pipeline_version": run.pipeline_version,
                    "canonical_schema_version": run.canonical_schema_version,
                    "frozen_page_count": len(page_numbers),
                    "frozen_entry_page_count": len(required_entry_page_numbers),
                    "frozen_pages_with_blocks": len(block_pages),
                    "frozen_pages_with_entries": len(
                        required_entry_page_ids & entry_pages
                    ),
                    "frozen_pages_with_vocabulary": len(
                        required_entry_page_ids & vocabulary_pages
                    ),
                    "source_block_count": block_count,
                    "source_entry_count": entry_count,
                    "vocabulary_entry_count": vocabulary_count,
                    "missing_pages": sorted(missing_pages),
                    "render_sha256_mismatches": sorted(render_mismatches),
                    "pages_without_blocks": pages_without_blocks,
                    "pages_without_entries": pages_without_entries,
                    "pages_without_vocabulary": pages_without_vocabulary,
                    "blockers": blockers,
                    "ready_for_gold_draft": not blockers,
                }
            )
    return results
