import hashlib

import fitz
import pytest

from app.db import SessionLocal
from app.models import Artifact, ProvenanceRecord, ReviewTask, SourceMedia, VocabularyEntry
from app.services.extraction import extract_native_blocks
from app.services.gates import evaluate_source_media_gate
from app.services.gold import build_gold_dataset, serialize_gold_csv
from app.services.review import resolve_review_task
from app.services.segmentation import segment_source_entries
from app.services.source_media import (
    ROLE_ENTRY,
    ROLE_NON_VOCABULARY,
    ROLE_UNRESOLVED,
    PageBlock,
    associate_media,
    extract_source_media,
    source_media_metrics,
)
from app.services.structured_extraction import extract_canonical_fields
from app.services.validation import validate_canonical_entries
from app.storage import LocalStorageAdapter


def _block(y1, y2, *, entry=None, head=False, kinds=None, x1=0.1, x2=0.9):
    return PageBlock(
        y1=y1,
        y2=y2,
        x1=x1,
        x2=x2,
        kinds=kinds or (["ENTRY_HEAD"] if head else ["BODY_TEXT"]),
        starts_entry=head,
        entry_ids=[entry] if isinstance(entry, str) else list(entry or []),
    )


def _bbox(y1, y2, x1=0.4, x2=0.6):
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "unit": "normalized"}


ORDER = {"e1": 1, "e2": 2, "e3": 3}


def _decide(bbox, blocks, separators, previous=None):
    return associate_media(bbox, blocks, separators, entry_order=ORDER, previous_entry_id=previous)


def test_one_entry_one_image_is_bound_to_the_enclosing_entry():
    blocks = [
        _block(0.10, 0.12, entry="e1", head=True),
        _block(0.13, 0.20, entry="e1"),
        _block(0.42, 0.44, entry="e2", head=True),
    ]
    decision = _decide(_bbox(0.22, 0.38), blocks, [0.09, 0.40])
    assert (decision.role, decision.source_entry_id) == (ROLE_ENTRY, "e1")
    assert decision.verification_status == "AUTO_VERIFIED"
    assert decision.warnings == []


def test_one_entry_with_multiple_images_binds_each_to_the_same_entry():
    blocks = [_block(0.10, 0.20, entry="e1", head=True), _block(0.72, 0.74, entry="e2", head=True)]
    separators = [0.09, 0.70]
    first = _decide(_bbox(0.22, 0.40), blocks, separators)
    second = _decide(_bbox(0.45, 0.65), blocks, separators)
    assert first.source_entry_id == second.source_entry_id == "e1"


def test_multiple_entries_each_keep_their_own_image():
    blocks = [
        _block(0.05, 0.10, entry="e1", head=True),
        _block(0.32, 0.36, entry="e2", head=True),
        _block(0.62, 0.66, entry="e3", head=True),
    ]
    separators = [0.04, 0.30, 0.60, 0.90]
    assert _decide(_bbox(0.12, 0.28), blocks, separators).source_entry_id == "e1"
    assert _decide(_bbox(0.38, 0.58), blocks, separators).source_entry_id == "e2"
    assert _decide(_bbox(0.68, 0.88), blocks, separators).source_entry_id == "e3"


def test_image_inside_an_entry_between_its_own_lines():
    blocks = [_block(0.10, 0.20, entry="e1", head=True), _block(0.42, 0.50, entry="e1")]
    decision = _decide(_bbox(0.22, 0.40), blocks, [0.09, 0.60])
    assert (decision.role, decision.source_entry_id) == (ROLE_ENTRY, "e1")


def test_two_column_layout_is_never_guessed():
    blocks = [
        _block(0.10, 0.30, entry="e1", head=True, x1=0.05, x2=0.45),
        _block(0.10, 0.30, entry="e2", head=True, x1=0.55, x2=0.95),
    ]
    decision = _decide(_bbox(0.32, 0.45, x1=0.1, x2=0.4), blocks, [0.09, 0.50])
    assert decision.role == ROLE_UNRESOLVED
    assert decision.verification_status == "REVIEW_REQUIRED"
    assert "multi_column_layout" in decision.warnings


def test_image_between_entries_with_rules_on_both_sides_is_ambiguous():
    blocks = [_block(0.10, 0.20, entry="e1", head=True), _block(0.52, 0.56, entry="e2", head=True)]
    decision = _decide(_bbox(0.25, 0.45), blocks, [0.09, 0.22, 0.50])
    assert decision.role == ROLE_UNRESOLVED
    assert decision.source_entry_id is None
    assert decision.candidate_entry_ids == ["e1", "e2"]
    assert "separator_between_entry_text_and_media" in decision.warnings


def test_image_without_separator_before_next_headword_is_ambiguous():
    blocks = [_block(0.10, 0.20, entry="e1", head=True), _block(0.52, 0.56, entry="e2", head=True)]
    decision = _decide(_bbox(0.25, 0.45), blocks, [0.09])
    assert decision.verification_status == "REVIEW_REQUIRED"
    assert "no_separator_before_next_entry" in decision.warnings


def test_page_level_illustration_is_not_vocabulary_media():
    decision = _decide(_bbox(0.0, 1.0, x1=0.0, x2=1.0), [], [])
    assert (decision.role, decision.reason) == (ROLE_NON_VOCABULARY, "FULL_PAGE_IMAGE")
    assert decision.verification_status == "AUTO_VERIFIED"


def test_word_list_header_resource_is_not_vocabulary_media():
    blocks = [
        _block(0.15, 0.20, kinds=["WORD_LIST_HEADER"]),
        _block(0.65, 0.68, kinds=["PREVIEW_TABLE_HEADER"]),
    ]
    decision = _decide(_bbox(0.25, 0.40), blocks, [])
    assert (decision.role, decision.reason) == (ROLE_NON_VOCABULARY, "WORD_LIST_HEADER_RESOURCE")


def test_decorative_image_without_entry_context_goes_to_review():
    blocks = [_block(0.30, 0.35, kinds=["BODY_TEXT"])]
    decision = _decide(_bbox(0.05, 0.25), blocks, [])
    assert decision.role == ROLE_UNRESOLVED
    assert decision.reason == "NO_ENTRY_CONTEXT"
    assert decision.candidate_entry_ids == []


def test_cross_page_entry_image_at_top_of_next_page():
    # The entry text ended on the previous page; its illustration opens this one.
    blocks = [_block(0.30, 0.34, entry="e2", head=True), _block(0.95, 0.97, kinds=["PAGE_NUMBER"])]
    decision = _decide(_bbox(0.08, 0.24), blocks, [0.27], previous="e1")
    assert (decision.role, decision.source_entry_id) == (ROLE_ENTRY, "e1")


def test_cross_page_entry_image_above_continuing_text():
    blocks = [_block(0.30, 0.40, entry="e1"), _block(0.52, 0.56, entry="e2", head=True)]
    decision = _decide(_bbox(0.08, 0.26), blocks, [0.50], previous="e1")
    assert (decision.role, decision.source_entry_id) == (ROLE_ENTRY, "e1")


def test_top_of_page_image_is_ambiguous_when_owner_is_not_adjacent_to_next_headword():
    blocks = [_block(0.30, 0.34, entry="e3", head=True)]
    decision = _decide(_bbox(0.08, 0.24), blocks, [0.27], previous="e1")
    assert decision.verification_status == "REVIEW_REQUIRED"
    assert "owner_is_not_the_entry_preceding_next_headword" in decision.warnings


def _png(color: tuple[int, int, int]) -> bytes:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 48, 48), False)
    pixmap.set_rect(pixmap.irect, color)
    return pixmap.tobytes("png")


def _media_pdf(*, ambiguous: bool = False) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    width = page.rect.width

    def rule(y):
        page.draw_line((60, y), (width - 60, y), width=0.5)

    rule(60)
    page.insert_text((72, 80), "apple [apl]")
    page.insert_text((72, 100), "n. fruit")
    page.insert_image(fitz.Rect(250, 120, 340, 210), stream=_png((200, 30, 30)))
    if ambiguous:
        rule(115)
    rule(230)
    page.insert_text((72, 250), "berry [beri]")
    page.insert_text((72, 270), "n. small fruit")
    page.insert_image(fitz.Rect(250, 290, 340, 380), stream=_png((30, 30, 200)))
    page.insert_image(fitz.Rect(250, 390, 340, 480), stream=_png((30, 200, 30)))
    rule(500)
    page.insert_text((72, 520), "cherry [cheri]")
    page.insert_text((72, 540), "n. stone fruit")
    payload = doc.tobytes()
    doc.close()
    return payload


def _run_to_media(client, payload: bytes, tmp_path):
    run_id = client.post(
        "/api/v1/documents", files={"file": ("media.pdf", payload, "application/pdf")}
    ).json()["run_id"]
    db = SessionLocal()
    storage = LocalStorageAdapter(tmp_path)
    extract_native_blocks(db, run_id)
    segment_source_entries(db, run_id)
    extract_canonical_fields(db, run_id)
    result = extract_source_media(db, run_id, storage=storage)
    return db, run_id, storage, result


def _media(db, run_id):
    return (
        db.query(SourceMedia)
        .filter(SourceMedia.processing_run_id == run_id)
        .order_by(SourceMedia.page_number, SourceMedia.media_order)
        .all()
    )


def test_pipeline_extracts_hashes_stores_and_binds_source_media(client, tmp_path):
    db, run_id, storage, result = _run_to_media(client, _media_pdf(), tmp_path)
    try:
        assert result["media_detected"] == result["media_created"] == 3
        rows = _media(db, run_id)
        lemmas = {
            item.id: item.lemma
            for item in db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id)
        }
        assert [lemmas[row.vocabulary_entry_id] for row in rows] == ["apple", "berry", "berry"]
        assert {row.media_role for row in rows} == {ROLE_ENTRY}
        assert len({row.sha256 for row in rows}) == 3
        for row in rows:
            artifact = db.get(Artifact, row.artifact_id)
            assert artifact.artifact_type == "SOURCE_MEDIA"
            assert artifact.metadata_json["namespace"] == "SOURCE_MEDIA"
            assert hashlib.sha256(storage.read_bytes(artifact.object_key)).hexdigest() == row.sha256
            provenance = {
                item.target_field_path: item.provenance_type
                for item in db.query(ProvenanceRecord).filter(
                    ProvenanceRecord.target_entity_type == "SourceMedia",
                    ProvenanceRecord.target_entity_id == row.id,
                )
            }
            assert provenance == {"artifact": "SOURCE_DIRECT", "source_entry_id": "SOURCE_LAYOUT"}
        metrics = source_media_metrics(db, run_id, storage=storage)
        assert metrics["media_persisted"] == metrics["associated_with_vocabulary_entry"] == 3
        for name in (
            "missing_media",
            "missing_artifact",
            "missing_sha256",
            "broken_artifact",
            "broken_provenance",
            "unbound_media",
            "unresolved_media",
        ):
            assert metrics[name] == 0
    finally:
        db.close()


def test_rerun_is_idempotent_and_never_changes_hashes(client, tmp_path):
    db, run_id, storage, _ = _run_to_media(client, _media_pdf(), tmp_path)
    try:
        before = [(row.id, row.sha256, row.source_entry_id) for row in _media(db, run_id)]
        artifacts = db.query(Artifact).filter(Artifact.artifact_type == "SOURCE_MEDIA").count()
        again = extract_source_media(db, run_id, storage=storage)
        assert (again["media_created"], again["media_reused"]) == (0, 3)
        assert [(row.id, row.sha256, row.source_entry_id) for row in _media(db, run_id)] == before
        assert (
            db.query(Artifact).filter(Artifact.artifact_type == "SOURCE_MEDIA").count() == artifacts
        )
    finally:
        db.close()


def test_artifact_corruption_is_detected_by_the_media_gate(client, tmp_path, monkeypatch):
    db, run_id, storage, _ = _run_to_media(client, _media_pdf(), tmp_path)
    try:
        artifact = db.get(Artifact, _media(db, run_id)[0].artifact_id)
        storage.put_bytes(artifact.object_key, b"tampered")
        assert source_media_metrics(db, run_id, storage=storage)["broken_artifact"] == 1
        storage.delete(artifact.object_key)
        assert source_media_metrics(db, run_id, storage=storage)["missing_artifact"] == 1
        monkeypatch.setattr(
            "app.services.gates.source_media_metrics",
            lambda db, run_id: source_media_metrics(db, run_id, storage=storage),
        )
        gate = evaluate_source_media_gate(db, run_id)
        assert gate["status"] == "FAIL"
        assert "missing_artifact" in gate["blocking_failures"]
    finally:
        db.close()


def test_ambiguous_media_is_queued_and_human_decision_survives_rerun(client, tmp_path):
    db, run_id, storage, _ = _run_to_media(client, _media_pdf(ambiguous=True), tmp_path)
    try:
        rows = _media(db, run_id)
        ambiguous = rows[0]
        assert ambiguous.media_role == ROLE_UNRESOLVED
        assert ambiguous.source_entry_id is None
        task = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.target_entity_type == "SourceMedia",
                ReviewTask.target_entity_id == ambiguous.id,
            )
            .one()
        )
        assert task.status == "OPEN"
        validate_canonical_entries(db, run_id)
        with pytest.raises(ValueError, match="open review tasks"):
            build_gold_dataset(db, run_id)

        apple = task.source_context["candidate_entry_ids"][0]
        result = resolve_review_task(
            db,
            task.id,
            resolution={"decision": "ACCEPT", "source_entry_id": apple},
            reviewer_id="reviewer-1",
        )
        assert result["verification_status"] == "HUMAN_VERIFIED"
        assert result["source_entry_id"] == apple
        extract_source_media(db, run_id, storage=storage)
        db.refresh(ambiguous)
        assert ambiguous.verification_status == "HUMAN_VERIFIED"
        assert ambiguous.source_entry_id == apple
        assert (
            db.query(ProvenanceRecord)
            .filter(
                ProvenanceRecord.target_entity_id == ambiguous.id,
                ProvenanceRecord.provenance_type == "HUMAN_REVIEW",
            )
            .count()
            == 1
        )

        dataset = build_gold_dataset(db, run_id)
        assert dataset["schema_version"] == "1.1"
        assert dataset["source_media_count"] == 3
        by_lemma = {record["lemma"]: record for record in dataset["records"]}
        assert [len(by_lemma[name]["source_media"]) for name in ("apple", "berry", "cherry")] == [
            1,
            2,
            0,
        ]
        media = by_lemma["apple"]["source_media"][0]
        assert media["namespace"] == "SOURCE_MEDIA"
        assert media["sha256"] == ambiguous.sha256
        assert media["artifact"]["object_key"].startswith("source-media/")
        assert media["provenance"]["source_entry_id"] == apple
        header, apple_row = serialize_gold_csv(dataset).decode().splitlines()[:2]
        assert header.endswith("source_pages,source_media_count,source_media_refs,source_media_sha256")
        assert ambiguous.sha256 in apple_row
    finally:
        db.close()


def test_human_can_mark_media_as_not_vocabulary(client, tmp_path):
    db, run_id, _, _ = _run_to_media(client, _media_pdf(ambiguous=True), tmp_path)
    try:
        task = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id).one()
        result = resolve_review_task(
            db,
            task.id,
            resolution={"decision": "ACCEPT", "classification": "NOT_VOCABULARY_MEDIA"},
            reviewer_id="reviewer-1",
        )
        assert result["media_role"] == ROLE_NON_VOCABULARY
        assert result["source_entry_id"] is None
        assert source_media_metrics(db, run_id, verify_bytes=False)["unresolved_media"] == 0
    finally:
        db.close()


def test_source_media_api_lists_and_serves_original_bytes(client, tmp_path, monkeypatch):
    monkeypatch.setenv("VIE_STORAGE_ROOT", str(tmp_path))
    from app.settings import get_settings

    get_settings.cache_clear()
    try:
        payload = _media_pdf()
        run_id = client.post(
            "/api/v1/documents", files={"file": ("media.pdf", payload, "application/pdf")}
        ).json()["run_id"]
        executed = client.post(f"/api/v1/runs/{run_id}/execute").json()
        assert executed["status"] == "COMPLETED"
        assert any(stage["stage"] == "G3_MEDIA" for stage in executed["stages"])
        listing = client.get(f"/api/v1/runs/{run_id}/source-media").json()
        assert listing["metrics"]["media_persisted"] == 3
        item = listing["items"][0]
        content = client.get(item["content_url"])
        assert content.status_code == 200
        assert hashlib.sha256(content.content).hexdigest() == item["sha256"]
        gold = client.get(f"/api/v1/runs/{run_id}/gold").json()
        assert gold["source_media_count"] == 3
    finally:
        get_settings.cache_clear()
