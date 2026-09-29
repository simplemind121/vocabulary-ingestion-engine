from __future__ import annotations

import pytest

from app.services.gold_prediction_contract import build_gold_prediction, validate_gold_prediction


_SHA = "a" * 64
_PAGE_SHA = "b" * 64


def _scaffold() -> dict:
    return {
        "document_sha256": _SHA,
        "page_number": 7,
        "page_image_sha256": _PAGE_SHA,
        "review_status": "DRAFT",
    }


def test_build_prediction_preserves_frozen_page_identity() -> None:
    prediction = build_gold_prediction(
        _scaffold(),
        blocks=[{"raw_text": "abandon"}],
        entries=[{"display_form": "abandon"}],
        vocabulary=[{"lemma": "abandon"}],
    )

    assert prediction["document_sha256"] == _SHA
    assert prediction["page_number"] == 7
    assert prediction["page_image_sha256"] == _PAGE_SHA
    assert "review_status" not in prediction


def test_prediction_requires_source_identity() -> None:
    prediction = build_gold_prediction(_scaffold(), blocks=[], entries=[], vocabulary=[])
    prediction["page_image_sha256"] = None

    with pytest.raises(ValueError, match="prediction_page_image_sha256_required"):
        validate_gold_prediction(prediction)


def test_prediction_rejects_non_object_payload_items() -> None:
    with pytest.raises(TypeError, match="prediction_blocks_items_must_be_objects"):
        build_gold_prediction(
            _scaffold(),
            blocks=["not-source-block"],  # type: ignore[list-item]
            entries=[],
            vocabulary=[],
        )
