import pytest

from app.services.gold_preannotation_batch import build_machine_annotation_batch


def _scaffolds():
    return [
        {
            "sample_id": f"gold-v1-p{page:04d}",
            "document_sha256": "a" * 64,
            "page_number": page,
            "page_image_sha256": f"{page:064x}",
            "layout_tags": ["NORMAL"],
            "review_status": "DRAFT",
            "reviewer_id": None,
            "blocks": [],
            "entries": [],
            "vocabulary": [],
            "review_notes": [],
        }
        for page in range(1, 31)
    ]


def _predictions():
    return [
        {
            "document_sha256": "a" * 64,
            "page_number": page,
            "page_image_sha256": f"{page:064x}",
            "blocks": [{"text": f"page-{page}"}],
            "entries": [{"lemma": f"word-{page}", "raw_text": f"word-{page}"}],
            "vocabulary": [{"lemma": f"word-{page}"}],
        }
        for page in range(1, 31)
    ]


def test_build_machine_annotation_batch_preserves_draft_and_identity():
    drafts = build_machine_annotation_batch(
        _scaffolds(),
        list(reversed(_predictions())),
        generator="pipeline@0.1",
    )

    assert len(drafts) == 30
    assert [draft["page_number"] for draft in drafts] == list(range(1, 31))
    assert all(draft["review_status"] == "DRAFT" for draft in drafts)
    assert all(draft["reviewer_id"] is None for draft in drafts)
    assert all(
        any("MACHINE_PREANNOTATION_ONLY" in note for note in draft["review_notes"])
        for draft in drafts
    )


def test_batch_rejects_missing_prediction():
    with pytest.raises(ValueError, match="exactly_30_predictions"):
        build_machine_annotation_batch(
            _scaffolds(),
            _predictions()[:-1],
            generator="pipeline@0.1",
        )


def test_batch_rejects_page_image_identity_drift():
    predictions = _predictions()
    predictions[7]["page_image_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="prediction_identity_mismatch:8:page_image_sha256"):
        build_machine_annotation_batch(
            _scaffolds(),
            predictions,
            generator="pipeline@0.1",
        )


def test_batch_rejects_source_document_identity_drift():
    predictions = _predictions()
    predictions[0]["document_sha256"] = "b" * 64

    with pytest.raises(ValueError, match="prediction_identity_mismatch:1:document_sha256"):
        build_machine_annotation_batch(
            _scaffolds(),
            predictions,
            generator="pipeline@0.1",
        )


def test_batch_rejects_non_draft_scaffold():
    scaffolds = _scaffolds()
    scaffolds[0]["review_status"] = "HUMAN_VERIFIED"

    with pytest.raises(ValueError, match="scaffold_must_be_draft:1"):
        build_machine_annotation_batch(
            scaffolds,
            _predictions(),
            generator="pipeline@0.1",
        )
