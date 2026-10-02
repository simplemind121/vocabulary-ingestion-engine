import json
from pathlib import Path

import pytest

from app.services.gold_annotation import promote_annotation_to_human_verified
from app.services.gold_corpus import (
    build_annotation_corpus,
    evaluate_corpus_readiness,
    freeze_manifest,
)
from app.services.gold_sample import REQUIRED_LAYOUT_TAGS

ROOT = Path(__file__).resolve().parents[1]


def _plan_and_hashes():
    tags = sorted(REQUIRED_LAYOUT_TAGS)
    candidates = []
    hashes = {}
    for index in range(30):
        page = index + 1
        candidates.append(
            {"pdf_page": page, "tags": [tags[index]] if index < len(tags) else ["NORMAL"]}
        )
        hashes[str(page)] = f"{page:064x}"[-64:]
    return {
        "source_document_sha256": "a" * 64,
        "candidates": candidates,
    }, {"pages": hashes}


def test_corpus_scaffolds_are_not_allowed_to_freeze():
    plan, hashes = _plan_and_hashes()
    corpus = build_annotation_corpus(plan, hashes)
    readiness = evaluate_corpus_readiness(corpus)
    assert readiness["annotation_count"] == 30
    assert readiness["human_verified_count"] == 0
    assert readiness["status"] == "NOT_READY"
    with pytest.raises(ValueError, match="cannot freeze"):
        freeze_manifest(corpus)


def test_30_complete_human_verified_annotations_freeze_manifest():
    plan, hashes = _plan_and_hashes()
    corpus = build_annotation_corpus(plan, hashes)
    verified = []
    for annotation in corpus:
        annotation["blocks"] = [{"text": "source block"}]
        annotation["entries"] = [{"lemma": "word", "raw_text": "source block"}]
        annotation["vocabulary"] = [{"lemma": "word"}]
        verified.append(
            promote_annotation_to_human_verified(
                annotation,
                reviewer_id="human-reviewer",
                page_image_sha256=annotation["page_image_sha256"],
            )
        )
    readiness = evaluate_corpus_readiness(verified)
    assert readiness["status"] == "READY_TO_FREEZE"
    assert readiness["human_verified_count"] == 30
    manifest = freeze_manifest(verified)
    assert manifest["dataset_version"] == "1.0"
    assert manifest["freeze_status"] == "FROZEN"
    assert len(manifest["pages"]) == 30
    assert len(manifest["manifest_sha256"]) == 64
    assert all(page["review_status"] == "HUMAN_VERIFIED" for page in manifest["pages"])


def test_repository_corpus_truthfully_reports_frozen_verified_dataset():
    annotations = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((ROOT / "gold_samples" / "annotations").glob("*.json"))
    ]

    readiness = evaluate_corpus_readiness(annotations)

    assert readiness["annotation_count"] == 30
    assert readiness["human_verified_count"] == 30
    assert readiness["missing_layout_tags"] == []
    assert readiness["status"] == "READY_TO_FREEZE"
    assert readiness["errors"] == []
