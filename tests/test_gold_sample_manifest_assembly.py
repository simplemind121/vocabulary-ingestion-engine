import pytest

from app.services.gold_sample_manifest import (
    assemble_and_validate_gold_sample_manifest,
    assemble_gold_sample_manifest,
)


def _verified(sample_id: str, page_number: int, tag: str) -> dict:
    return {
        "annotation_schema_version": "1.0",
        "sample_id": sample_id,
        "document_sha256": "a" * 64,
        "page_number": page_number,
        "layout_tags": [tag],
        "review_status": "HUMAN_VERIFIED",
        "reviewer_id": "reviewer-1",
        "page_image_sha256": "b" * 64,
        "blocks": [{"text": "block"}],
        "entries": [{"raw_text": "entry"}],
        "vocabulary": [{"lemma": "entry"}],
        "review_notes": [],
    }


def test_manifest_assembly_rejects_draft_annotation():
    annotation = _verified("sample-001", 1, "NORMAL")
    annotation["review_status"] = "DRAFT"
    with pytest.raises(ValueError, match="not verified ground truth"):
        assemble_gold_sample_manifest(
            [annotation],
            ground_truth_paths={"sample-001": "ground_truth/sample-001.json"},
        )


def test_manifest_assembly_rejects_missing_ground_truth_path():
    with pytest.raises(ValueError, match="ground truth path missing"):
        assemble_gold_sample_manifest(
            [_verified("sample-001", 1, "NORMAL")],
            ground_truth_paths={},
        )


def test_thirty_verified_annotations_can_form_valid_manifest():
    required = [
        "NORMAL",
        "DOUBLE_COLUMN",
        "IPA_DENSE",
        "IMAGE",
        "SPECIAL_LAYOUT",
        "BOUNDARY_ENTRY",
        "CROSS_PAGE_ENTRY",
        "TABLE",
        "INDEX",
        "OCR_HARD",
    ]
    annotations = []
    paths = {}
    for index in range(30):
        sample_id = f"sample-{index + 1:03d}"
        tag = required[index] if index < len(required) else "NORMAL"
        annotations.append(_verified(sample_id, index + 1, tag))
        paths[sample_id] = f"ground_truth/{sample_id}.json"

    manifest, validation = assemble_and_validate_gold_sample_manifest(
        annotations,
        ground_truth_paths=paths,
    )
    assert manifest["dataset_version"] == "1.0"
    assert len(manifest["pages"]) == 30
    assert validation["status"] == "PASS"
    assert validation["human_verified_pages"] == 30
    assert validation["missing_layout_tags"] == []
