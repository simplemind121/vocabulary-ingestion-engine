import pytest

from app.services.gold_annotation import (
    build_annotation_scaffold,
    promote_annotation_to_human_verified,
    validate_ground_truth_annotation,
)

SHA = "a" * 64
PAGE_SHA = "b" * 64


def _scaffold():
    return build_annotation_scaffold(
        sample_id="gs-0001",
        document_sha256=SHA,
        page_number=220,
        layout_tags=["NORMAL", "CROSS_PAGE_ENTRY"],
    )


def test_scaffold_is_explicitly_draft_and_cannot_masquerade_as_verified():
    annotation = _scaffold()
    assert annotation["review_status"] == "DRAFT"
    assert annotation["reviewer_id"] is None
    assert annotation["page_image_sha256"] is None
    assert validate_ground_truth_annotation(annotation)["status"] == "PASS"


def test_incomplete_annotation_cannot_be_promoted_to_human_verified():
    with pytest.raises(ValueError, match="cannot promote incomplete annotation"):
        promote_annotation_to_human_verified(
            _scaffold(), reviewer_id="reviewer-1", page_image_sha256=PAGE_SHA
        )


def test_complete_annotation_can_be_promoted_only_with_reviewer_and_page_hash():
    annotation = _scaffold()
    annotation["blocks"] = [{"text": "sample [ˈsɑːmpl]"}]
    annotation["entries"] = [{"lemma": "sample", "raw_text": "sample [ˈsɑːmpl]"}]
    annotation["vocabulary"] = [
        {
            "lemma": "sample",
            "display_form": "sample",
            "ipa": "ˈsɑːmpl",
            "part_of_speech": "n.",
            "definition": "样本",
        }
    ]
    verified = promote_annotation_to_human_verified(
        annotation, reviewer_id="reviewer-1", page_image_sha256=PAGE_SHA
    )
    assert verified["review_status"] == "HUMAN_VERIFIED"
    assert verified["reviewer_id"] == "reviewer-1"
    assert validate_ground_truth_annotation(verified)["status"] == "PASS"


def test_human_verified_non_entry_page_can_truthfully_have_no_entries():
    annotation = build_annotation_scaffold(
        sample_id="gold-v1-p0120",
        document_sha256=SHA,
        page_number=120,
        layout_tags=["TABLE", "SPECIAL_LAYOUT"],
    )
    annotation["blocks"] = [{"type": "TABLE", "text": "root/affix preview"}]

    verified = promote_annotation_to_human_verified(
        annotation,
        reviewer_id="reviewer-1",
        page_image_sha256=PAGE_SHA,
    )

    assert verified["entries"] == []
    assert verified["vocabulary"] == []
    assert validate_ground_truth_annotation(verified)["status"] == "PASS"


def test_human_verified_normal_page_cannot_omit_entries():
    annotation = build_annotation_scaffold(
        sample_id="gold-v1-p0030",
        document_sha256=SHA,
        page_number=30,
        layout_tags=["NORMAL"],
    )
    annotation["blocks"] = [{"text": "source block"}]

    with pytest.raises(ValueError, match="entries_required_for_entry_bearing_page"):
        promote_annotation_to_human_verified(
            annotation,
            reviewer_id="reviewer-1",
            page_image_sha256=PAGE_SHA,
        )


def test_verified_annotation_rejects_missing_page_image_digest():
    annotation = _scaffold()
    annotation.update(
        {
            "review_status": "HUMAN_VERIFIED",
            "reviewer_id": "reviewer-1",
            "blocks": [{"text": "x"}],
            "entries": [{"lemma": "x", "raw_text": "x"}],
            "vocabulary": [{"lemma": "x"}],
        }
    )
    result = validate_ground_truth_annotation(annotation)
    assert result["status"] == "FAIL"
    assert "page_image_sha256_required_for_human_verified" in result["errors"]
