from pathlib import Path

from app.services.full_book_evidence import (
    audit_pipeline_sha256,
    build_redacted_full_book_evidence,
    validate_redacted_full_book_evidence,
)
from app.services.gold_annotation import (
    build_annotation_scaffold,
    promote_annotation_to_human_verified,
)
from app.services.gold_corpus import freeze_manifest
from app.services.gold_sample import REQUIRED_LAYOUT_TAGS
from app.services.release_readiness import (
    REQUIRED_PRODUCTION_CHECKS,
    evaluate_g6_release_readiness,
)
from tests.media_helpers import (
    media_item,
    media_predictions,
    source_media_evidence,
    verified_media_overlays,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "a" * 64
GIT_SHA = "b" * 40


def _verified_annotations():
    tags = sorted(REQUIRED_LAYOUT_TAGS)
    result = []
    for index in range(30):
        page = index + 1
        annotation = build_annotation_scaffold(
            sample_id=f"gold-v1-p{page:04d}",
            document_sha256=SOURCE_SHA,
            page_number=page,
            layout_tags=[tags[index]] if index < len(tags) else ["NORMAL"],
        )
        annotation["page_image_sha256"] = f"{page:064x}"[-64:]
        annotation["blocks"] = [{"text": "reviewed source"}]
        if set(annotation["layout_tags"]) & {
            "NORMAL",
            "BOUNDARY_ENTRY",
            "CROSS_PAGE_ENTRY",
        }:
            annotation["entries"] = [{"lemma": "word", "raw_text": "word n. meaning"}]
            annotation["vocabulary"] = [{"lemma": "word"}]
        result.append(
            promote_annotation_to_human_verified(
                annotation,
                reviewer_id="human-reviewer",
                page_image_sha256=annotation["page_image_sha256"],
            )
        )
    return result


def _full_book_evidence():
    return {
        "evidence_schema_version": "1.0",
        "audit_pipeline_sha256": audit_pipeline_sha256(ROOT),
        "private_audit_report_sha256": "c" * 64,
        "audit_schema_version": "1.0",
        "status": "REVIEW_REQUIRED",
        "source_document_sha256": SOURCE_SHA,
        "source_page_count": 30,
        "native_text_pages": 29,
        "ocr_engine": "tesseract",
        "ocr_pages_attempted": 1,
        "ocr_text_pages": 1,
        "page_representation_coverage": 1.0,
        "unrepresented_pages": [],
        "source_block_count": 100,
        "ocr_source_block_count": 1,
        "low_confidence_ocr_block_count": 1,
        "entry_candidate_count": 10,
        "parsed_entry_count": 10,
        "cross_page_entry_count": 2,
        "review_queue_count": 1,
        "review_queue": [
            {
                "page_numbers": [1],
                "reasons": ["LOW_OCR_CONFIDENCE"],
                "source_block_id": "ocr-p0001-b0000",
                "confidence": 0.8,
            }
        ],
        "copyrighted_excerpts_included": False,
    }


def _benchmark(manifest_sha256):
    return {
        "benchmark_schema_version": "1.0",
        "dataset_version": "1.0",
        "status": "PASS",
        "page_count": 30,
        "exact_match": True,
        "failed_samples": [],
        "source_document_sha256": SOURCE_SHA,
        "gold_manifest_sha256": manifest_sha256,
        "layers": {
            "ocr": {"f1": 1.0},
            "segmentation": {"f1": 1.0},
            "canonical": {"field_accuracy": 1.0},
        },
    }


def _production_smoke():
    return {
        "evidence_schema_version": "1.0",
        "status": "PASS",
        "git_sha": GIT_SHA,
        "image_id": "sha256:" + "d" * 64,
        "upgrade_from_git_sha": "e" * 40,
        "upgrade_from_image_id": "sha256:" + "f" * 64,
        "recovery_state_sha256": "1" * 64,
        "checks": sorted(REQUIRED_PRODUCTION_CHECKS),
    }


def _media(annotations):
    predictions = media_predictions(
        annotations,
        {1: [media_item(1, lemma=None, seed=901)], 12: [media_item(1, lemma="word", seed=902)]},
    )
    return verified_media_overlays(annotations, predictions), predictions


def _evaluate(annotations, **overrides):
    verified = _verified_annotations()
    overlays, predictions = _media(verified)
    manifest = freeze_manifest(verified, overlays)
    values = {
        "media_annotations": overlays,
        "media_predictions": predictions,
        "source_media_evidence": source_media_evidence(
            source_sha=SOURCE_SHA,
            pages=30,
            entries=_full_book_evidence()["parsed_entry_count"],
        ),
        "annotations": annotations,
        "source_metadata": {
            "document_sha256": SOURCE_SHA,
            "pdf_page_count": 30,
        },
        "manifest": manifest,
        "benchmark_report": _benchmark(manifest["manifest_sha256"]),
        "full_book_evidence": _full_book_evidence(),
        "production_smoke": _production_smoke(),
        "repository_root": ROOT,
        "expected_git_sha": GIT_SHA,
    }
    values.update(overrides)
    return evaluate_g6_release_readiness(**values)


def test_g6_release_passes_only_when_all_evidence_is_current_and_verified():
    annotations = _verified_annotations()

    result = _evaluate(annotations, manifest=freeze_manifest(annotations, _media(annotations)[0]))

    assert result["status"] == "PASS"
    assert result["publish_allowed"] is True
    assert result["blocking_failures"] == []
    assert result["metrics"]["outstanding_full_book_reviews"] == 0


def test_g6_release_fails_closed_for_draft_gold_and_outstanding_book_review():
    annotations = _verified_annotations()
    annotations[0] = {**annotations[0], "review_status": "DRAFT", "reviewer_id": None}

    result = _evaluate(annotations)

    assert result["status"] == "FAIL"
    assert "gold_corpus_not_human_verified" in result["blocking_failures"]
    assert "frozen_manifest_unavailable" in result["blocking_failures"]
    assert "full_book_reviews_outstanding" in result["blocking_failures"]


def test_g6_release_rejects_stale_full_book_pipeline_evidence():
    annotations = _verified_annotations()
    evidence = _full_book_evidence()
    evidence["audit_pipeline_sha256"] = "e" * 64

    result = _evaluate(
        annotations,
        manifest=freeze_manifest(annotations),
        full_book_evidence=evidence,
    )

    assert "full_book_audit_stale_for_pipeline" in result["blocking_failures"]


def test_g6_release_requires_upgrade_and_rollback_evidence():
    annotations = _verified_annotations()
    production_smoke = _production_smoke()
    production_smoke["checks"].remove("upgrade_rollback")

    result = _evaluate(
        annotations,
        manifest=freeze_manifest(annotations),
        production_smoke=production_smoke,
    )

    assert result["status"] == "FAIL"
    assert "production_smoke_checks_incomplete" in result["blocking_failures"]


def test_g6_release_rejects_unbound_upgrade_and_rollback_evidence():
    annotations = _verified_annotations()
    production_smoke = _production_smoke()
    production_smoke["upgrade_from_git_sha"] = GIT_SHA

    result = _evaluate(
        annotations,
        manifest=freeze_manifest(annotations),
        production_smoke=production_smoke,
    )

    assert result["status"] == "FAIL"
    assert "upgrade_rollback_evidence_invalid" in result["blocking_failures"]


def test_full_book_release_evidence_removes_copyrighted_excerpts():
    report = {
        **{key: value for key, value in _full_book_evidence().items() if key not in {
            "evidence_schema_version",
            "audit_pipeline_sha256",
            "private_audit_report_sha256",
            "copyrighted_excerpts_included",
        }},
        "review_queue": [
            {
                "page_numbers": [1],
                "reasons": ["LOW_OCR_CONFIDENCE"],
                "source_block_id": "ocr-p0001-b0000",
                "confidence": 0.8,
                "raw_text_excerpt": "copyrighted source text",
            }
        ],
    }

    evidence = build_redacted_full_book_evidence(
        report,
        report_bytes=b"private report",
        repository_root=ROOT,
    )

    assert evidence["copyrighted_excerpts_included"] is False
    assert "raw_text_excerpt" not in evidence["review_queue"][0]

    validation = validate_redacted_full_book_evidence(
        evidence,
        source_metadata={"document_sha256": SOURCE_SHA, "pdf_page_count": 30},
        repository_root=ROOT,
    )
    assert validation == {"status": "PASS", "errors": []}
