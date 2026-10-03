import pytest

from app.services.gold_annotation import (
    build_annotation_scaffold,
    promote_annotation_to_human_verified,
)
from app.services.gold_preannotation import (
    build_machine_annotation_draft,
    summarize_review_work,
)


def _scaffold():
    scaffold = build_annotation_scaffold(
        sample_id="gold-v1-p0001",
        document_sha256="a" * 64,
        page_number=1,
        layout_tags=["NORMAL"],
    )
    scaffold["page_image_sha256"] = "b" * 64
    return scaffold


def test_machine_preannotation_never_claims_human_verified():
    draft = build_machine_annotation_draft(
        _scaffold(),
        {
            "blocks": [{"text": "medication"}],
            "entries": [{"lemma": "medication", "raw_text": "medication"}],
            "vocabulary": [{"lemma": "medication"}],
        },
        generator="pipeline@0.1",
    )

    assert draft["review_status"] == "DRAFT"
    assert draft["reviewer_id"] is None
    assert draft["blocks"][0]["text"] == "medication"
    assert any("MACHINE_PREANNOTATION_ONLY" in note for note in draft["review_notes"])


def test_human_promotion_remains_explicit_after_machine_preannotation():
    draft = build_machine_annotation_draft(
        _scaffold(),
        {
            "blocks": [{"text": "medication"}],
            "entries": [{"lemma": "medication", "raw_text": "medication"}],
            "vocabulary": [{"lemma": "medication"}],
        },
        generator="pipeline@0.1",
    )

    verified = promote_annotation_to_human_verified(
        draft,
        reviewer_id="reviewer-1",
        page_image_sha256=draft["page_image_sha256"],
    )
    assert verified["review_status"] == "HUMAN_VERIFIED"


def test_incomplete_machine_draft_cannot_be_promoted():
    draft = build_machine_annotation_draft(
        _scaffold(),
        {"blocks": [], "entries": [], "vocabulary": []},
        generator="pipeline@0.1",
    )
    with pytest.raises(ValueError, match="cannot promote incomplete annotation"):
        promote_annotation_to_human_verified(
            draft,
            reviewer_id="reviewer-1",
            page_image_sha256=draft["page_image_sha256"],
        )


def test_review_work_summary_exposes_required_checks():
    draft = build_machine_annotation_draft(
        _scaffold(),
        {
            "blocks": [{"text": "medication"}],
            "entries": [{"lemma": "medication", "raw_text": "medication"}],
            "vocabulary": [{"lemma": "medication"}],
        },
        generator="pipeline@0.1",
    )
    summary = summarize_review_work(draft)
    assert summary["page_number"] == 1
    assert summary["block_count"] == 1
    assert "cross_page_continuation" in summary["checks"]
    assert "no_machine_added_source_content" in summary["checks"]
