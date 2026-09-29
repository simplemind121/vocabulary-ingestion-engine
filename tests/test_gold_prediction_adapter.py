from __future__ import annotations

import pytest

from app.db import SessionLocal
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
from app.services.extraction import extract_native_blocks
from app.services.gold_prediction_adapter import build_gold_prediction_from_run


def _ingest_and_extract(client, sample_pdf_bytes) -> tuple[str, dict]:
    response = client.post(
        "/api/v1/documents",
        files={"file": ("gold-adapter.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        run = db.get(ProcessingRun, run_id)
        assert run is not None
        version = db.get(DocumentVersion, run.document_version_id)
        assert version is not None
        page = (
            db.query(Page)
            .filter(Page.document_version_id == version.id, Page.page_number == 1)
            .one()
        )
        render = db.get(Artifact, page.render_artifact_id)
        assert render is not None
        assert render.sha256 is not None
        scaffold = {
            "document_sha256": version.sha256,
            "page_number": 1,
            "page_image_sha256": render.sha256,
            "review_status": "DRAFT",
        }
        return run_id, scaffold
    finally:
        db.close()


def test_adapter_transports_persisted_source_blocks_without_promoting_truth(
    client, sample_pdf_bytes
) -> None:
    run_id, scaffold = _ingest_and_extract(client, sample_pdf_bytes)

    db = SessionLocal()
    try:
        prediction = build_gold_prediction_from_run(db, run_id, scaffold)
    finally:
        db.close()

    assert prediction["document_sha256"] == scaffold["document_sha256"]
    assert prediction["page_number"] == 1
    assert prediction["page_image_sha256"] == scaffold["page_image_sha256"]
    assert prediction["blocks"]
    assert any("abandon" in (block["raw_text"] or "") for block in prediction["blocks"])
    assert all(block["source_block_id"] for block in prediction["blocks"])
    assert prediction["entries"] == []
    assert prediction["vocabulary"] == []
    assert "review_status" not in prediction


def test_adapter_joins_persisted_entries_and_vocabulary_by_page_provenance(
    client, sample_pdf_bytes
) -> None:
    run_id, scaffold = _ingest_and_extract(client, sample_pdf_bytes)

    db = SessionLocal()
    try:
        run = db.get(ProcessingRun, run_id)
        assert run is not None
        block = (
            db.query(SourceBlock)
            .filter(SourceBlock.processing_run_id == run_id)
            .order_by(SourceBlock.reading_order, SourceBlock.id)
            .first()
        )
        assert block is not None
        entry = SourceEntry(
            document_version_id=run.document_version_id,
            processing_run_id=run_id,
            entry_order=1,
            raw_text=block.raw_text or "abandon",
            segmentation_confidence=0.99,
            status="PARSED",
        )
        db.add(entry)
        db.flush()
        db.add(
            SourceEntryBlock(
                source_entry_id=entry.id,
                source_block_id=block.id,
                block_order=1,
            )
        )
        vocabulary = VocabularyEntry(
            source_entry_id=entry.id,
            processing_run_id=run_id,
            lemma="abandon",
            display_form="abandon",
            verification_status="PARSED",
        )
        db.add(vocabulary)
        db.commit()

        prediction = build_gold_prediction_from_run(db, run_id, scaffold)
    finally:
        db.close()

    assert len(prediction["entries"]) == 1
    assert prediction["entries"][0]["source_entry_id"] == entry.id
    assert prediction["entries"][0]["source_block_ids"] == [block.id]
    assert len(prediction["vocabulary"]) == 1
    assert prediction["vocabulary"][0]["source_entry_id"] == entry.id
    assert prediction["vocabulary"][0]["lemma"] == "abandon"
    assert prediction["vocabulary"][0]["verification_status"] == "PARSED"
    assert "review_status" not in prediction


def test_adapter_rejects_document_identity_drift(client, sample_pdf_bytes) -> None:
    run_id, scaffold = _ingest_and_extract(client, sample_pdf_bytes)
    scaffold["document_sha256"] = "f" * 64

    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="gold_prediction_document_sha256_mismatch"):
            build_gold_prediction_from_run(db, run_id, scaffold)
    finally:
        db.close()


def test_adapter_rejects_render_identity_drift(client, sample_pdf_bytes) -> None:
    run_id, scaffold = _ingest_and_extract(client, sample_pdf_bytes)
    scaffold["page_image_sha256"] = "e" * 64

    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="gold_prediction_page_image_sha256_mismatch"):
            build_gold_prediction_from_run(db, run_id, scaffold)
    finally:
        db.close()
