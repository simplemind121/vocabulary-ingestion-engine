from __future__ import annotations

from app.models import (
    Artifact,
    Document,
    DocumentVersion,
    Page,
    ProcessingRun,
    SourceBlock,
    SourceEntry,
    VocabularyEntry,
)
from app.services.gold_run_preflight import inspect_gold_run_candidates


def test_preflight_reports_ready_persisted_run(db_session):
    artifact = Artifact(artifact_type="SOURCE_PDF", object_key="source.pdf", sha256="a" * 64)
    render = Artifact(artifact_type="PAGE_RENDER", object_key="page-1.png", sha256="b" * 64)
    document = Document(original_filename="private.pdf")
    db_session.add_all([artifact, render, document])
    db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        source_artifact_id=artifact.id,
        sha256="a" * 64,
        mime_type="application/pdf",
        file_size=1,
        page_count=1,
    )
    db_session.add(version)
    db_session.flush()
    page = Page(document_version_id=version.id, page_number=1, render_artifact_id=render.id)
    run = ProcessingRun(document_version_id=version.id, status="COMPLETED")
    db_session.add_all([page, run])
    db_session.flush()
    block = SourceBlock(
        page_id=page.id,
        processing_run_id=run.id,
        raw_text="abandon",
        bbox={},
        source_engine="fixture",
    )
    entry = SourceEntry(
        document_version_id=version.id,
        processing_run_id=run.id,
        entry_order=1,
        raw_text="abandon",
    )
    db_session.add_all([block, entry])
    db_session.flush()
    db_session.add(
        VocabularyEntry(
            source_entry_id=entry.id,
            processing_run_id=run.id,
            lemma="abandon",
        )
    )
    db_session.flush()

    candidates = inspect_gold_run_candidates(
        db_session,
        document_sha256="a" * 64,
        page_numbers=[1],
        page_image_sha256={1: "b" * 64},
    )

    assert len(candidates) == 1
    assert candidates[0]["processing_run_id"] == run.id
    assert candidates[0]["ready_for_gold_draft"] is True
    assert candidates[0]["blockers"] == []


def test_preflight_is_fail_closed_for_render_and_missing_pipeline_layers(db_session):
    artifact = Artifact(artifact_type="SOURCE_PDF", object_key="source-2.pdf", sha256="c" * 64)
    render = Artifact(artifact_type="PAGE_RENDER", object_key="page-2.png", sha256="d" * 64)
    document = Document(original_filename="private-2.pdf")
    db_session.add_all([artifact, render, document])
    db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        source_artifact_id=artifact.id,
        sha256="c" * 64,
        mime_type="application/pdf",
        file_size=1,
        page_count=1,
    )
    db_session.add(version)
    db_session.flush()
    page = Page(document_version_id=version.id, page_number=1, render_artifact_id=render.id)
    run = ProcessingRun(document_version_id=version.id, status="COMPLETED")
    db_session.add_all([page, run])
    db_session.flush()

    candidates = inspect_gold_run_candidates(
        db_session,
        document_sha256="c" * 64,
        page_numbers=[1],
        page_image_sha256={1: "e" * 64},
    )

    assert candidates[0]["ready_for_gold_draft"] is False
    assert candidates[0]["blockers"] == [
        "FROZEN_RENDER_SHA256_MISMATCH",
        "FROZEN_PAGES_WITHOUT_SOURCE_BLOCKS",
        "SOURCE_ENTRIES_MISSING",
        "VOCABULARY_ENTRIES_MISSING",
    ]
    assert candidates[0]["render_sha256_mismatches"] == [1]
