import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.services.gold_annotation import build_annotation_scaffold, promote_annotation_to_human_verified


def _schema():
    path = Path("gold_samples/annotation.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_annotation_scaffold_matches_json_schema():
    annotation = build_annotation_scaffold(
        sample_id="sample-001",
        document_sha256="a" * 64,
        page_number=10,
        layout_tags=["NORMAL"],
    )
    Draft202012Validator(_schema()).validate(annotation)
    assert annotation["review_status"] == "DRAFT"


def test_human_verified_schema_requires_real_ground_truth_content():
    annotation = build_annotation_scaffold(
        sample_id="sample-001",
        document_sha256="a" * 64,
        page_number=10,
        layout_tags=["NORMAL"],
    )
    annotation["blocks"] = [{"text": "medication"}]
    annotation["entries"] = [{"lemma": "medication", "raw_text": "medication"}]
    annotation["vocabulary"] = [{"lemma": "medication"}]
    verified = promote_annotation_to_human_verified(
        annotation,
        reviewer_id="reviewer-1",
        page_image_sha256="b" * 64,
    )
    Draft202012Validator(_schema()).validate(verified)
    assert verified["review_status"] == "HUMAN_VERIFIED"
