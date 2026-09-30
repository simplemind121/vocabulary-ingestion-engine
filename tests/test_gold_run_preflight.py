from __future__ import annotations

from app.db import SessionLocal
from app.models import Artifact, Document, DocumentVersion, Page, ProcessingRun, SourceBlock, SourceEntry, VocabularyEntry
from app.services.gold_run_preflight import inspect_gold_run_candidates


def _seed_candidate(db, *, source_sha: str, render_sha: str, populated: bool):
    artifact = Artifact(artifact_type="SOURCE_PDF", object_key=f"{source_sha}.pdf", sha256=source_sha)
    render = Artifact(artifact_type="PAGE_RENDER", object_key=f"{render_sha}.png", sha256=render_sha)
    document = Document(original_filename="private.pdf")
    db.add_all([artifact, render, document]); db.flush()
    version = DocumentVersion(document_id=document.id, version_no=1, source_artifact_id=artifact.id, sha256=source_sha, mime_type="application/pdf", file_size=1, page_count=1)
    db.add(version); db.flush()
    page = Page(document_version_id=version.id, page_number=1, render_artifact_id=render.id)
    run = ProcessingRun(document_version_id=version.id, status="COMPLETED")
    db.add_all([page, run]); db.flush()
    if populated:
        block = SourceBlock(page_id=page.id, processing_run_id=run.id, raw_text="abandon", bbox={}, source_engine="fixture")
        entry = SourceEntry(document_version_id=version.id, processing_run_id=run.id, entry_order=1, raw_text="abandon")
        db.add_all([block, entry]); db.flush()
        db.add(VocabularyEntry(source_entry_id=entry.id, processing_run_id=run.id, lemma="abandon")); db.flush()
    return run


def test_preflight_reports_ready_persisted_run(client) -> None:
    db = SessionLocal()
    try:
        run = _seed_candidate(db, source_sha="a" * 64, render_sha="b" * 64, populated=True)
        candidates = inspect_gold_run_candidates(db, document_sha256="a" * 64, page_numbers=[1], page_image_sha256={1: "b" * 64})
        assert len(candidates) == 1
        assert candidates[0]["processing_run_id"] == run.id
        assert candidates[0]["ready_for_gold_draft"] is True
        assert candidates[0]["blockers"] == []
    finally:
        db.rollback(); db.close()


def test_preflight_is_fail_closed_for_render_and_missing_pipeline_layers(client) -> None:
    db = SessionLocal()
    try:
        _seed_candidate(db, source_sha="c" * 64, render_sha="d" * 64, populated=False)
        candidates = inspect_gold_run_candidates(db, document_sha256="c" * 64, page_numbers=[1], page_image_sha256={1: "e" * 64})
        assert candidates[0]["ready_for_gold_draft"] is False
        assert candidates[0]["blockers"] == ["FROZEN_RENDER_SHA256_MISMATCH", "FROZEN_PAGES_WITHOUT_SOURCE_BLOCKS", "SOURCE_ENTRIES_MISSING", "VOCABULARY_ENTRIES_MISSING"]
        assert candidates[0]["render_sha256_mismatches"] == [1]
    finally:
        db.rollback(); db.close()
