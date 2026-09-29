import json
from pathlib import Path

import pytest

from app.services.gold_annotation_batch import build_annotation_scaffold_batch

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / "gold_samples" / name).read_text(encoding="utf-8"))


def test_real_gold_assets_build_exactly_30_bound_draft_scaffolds():
    selection = _load("selection_plan_v1.json")
    hashes = _load("page_image_hashes_v1.json")

    scaffolds = build_annotation_scaffold_batch(selection, hashes)

    assert len(scaffolds) == 30
    assert len({item["sample_id"] for item in scaffolds}) == 30
    assert len({item["page_number"] for item in scaffolds}) == 30
    assert all(item["review_status"] == "DRAFT" for item in scaffolds)
    assert all(item["reviewer_id"] is None for item in scaffolds)
    assert all(len(item["page_image_sha256"]) == 64 for item in scaffolds)
    assert all(item["blocks"] == [] for item in scaffolds)
    assert all(item["entries"] == [] for item in scaffolds)
    assert all(item["vocabulary"] == [] for item in scaffolds)


def test_batch_fails_closed_when_source_identity_differs():
    selection = _load("selection_plan_v1.json")
    hashes = _load("page_image_hashes_v1.json")
    hashes["source_document_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="source_document_sha256_mismatch"):
        build_annotation_scaffold_batch(selection, hashes)


def test_batch_fails_closed_when_a_selected_page_hash_is_missing():
    selection = _load("selection_plan_v1.json")
    hashes = _load("page_image_hashes_v1.json")
    hashes["pages"].pop(str(selection["candidates"][0]["pdf_page"]))

    with pytest.raises(ValueError, match="selected_pages_and_hash_registry_must_match"):
        build_annotation_scaffold_batch(selection, hashes)
