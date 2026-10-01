from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.gold_run_batch import (
    build_gold_draft_batch_from_run,
    build_gold_prediction_batch_from_run,
)


def _scaffolds() -> list[dict]:
    return [
        {
            "document_sha256": "a" * 64,
            "page_number": page,
            "page_image_sha256": f"{page:064x}",
            "review_status": "DRAFT",
        }
        for page in range(1, 31)
    ]


def _prediction(scaffold: dict) -> dict:
    return {
        "document_sha256": scaffold["document_sha256"],
        "page_number": scaffold["page_number"],
        "page_image_sha256": scaffold["page_image_sha256"],
        "blocks": [],
        "entries": [],
        "vocabulary": [],
    }


def test_prediction_batch_is_deterministic_and_uses_page_adapter() -> None:
    scaffolds = list(reversed(_scaffolds()))

    with patch(
        "app.services.gold_run_batch.build_gold_prediction_from_run",
        side_effect=lambda db, run_id, scaffold: _prediction(scaffold),
    ) as adapter:
        predictions = build_gold_prediction_batch_from_run(object(), "run-1", scaffolds)

    assert [item["page_number"] for item in predictions] == list(range(1, 31))
    assert adapter.call_count == 30


def test_prediction_batch_rejects_partial_gold_sample() -> None:
    with pytest.raises(ValueError, match="gold_sample_requires_exactly_30_scaffolds"):
        build_gold_prediction_batch_from_run(object(), "run-1", _scaffolds()[:-1])


def test_prediction_batch_rejects_duplicate_page_identity() -> None:
    scaffolds = _scaffolds()
    scaffolds[-1]["page_number"] = 1

    with pytest.raises(ValueError, match="scaffold_pages_must_be_unique_integers"):
        build_gold_prediction_batch_from_run(object(), "run-1", scaffolds)


def test_prediction_batch_rejects_non_draft_scaffold() -> None:
    scaffolds = _scaffolds()
    scaffolds[5]["review_status"] = "HUMAN_VERIFIED"

    with pytest.raises(ValueError, match="scaffold_must_be_draft:6"):
        build_gold_prediction_batch_from_run(object(), "run-1", scaffolds)


def test_draft_batch_preserves_machine_only_review_boundary() -> None:
    scaffolds = _scaffolds()

    with patch(
        "app.services.gold_run_batch.build_gold_prediction_from_run",
        side_effect=lambda db, run_id, scaffold: _prediction(scaffold),
    ):
        drafts = build_gold_draft_batch_from_run(
            object(),
            "run-1",
            scaffolds,
            generator="pipeline:test",
        )

    assert len(drafts) == 30
    assert all(item["review_status"] == "DRAFT" for item in drafts)
    assert all(item.get("reviewer_id") is None for item in drafts)
    assert all(
        any("MACHINE_PREANNOTATION_ONLY" in note for note in item["review_notes"])
        for item in drafts
    )
