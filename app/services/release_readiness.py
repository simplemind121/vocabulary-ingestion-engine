from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services.benchmark_gate import evaluate_benchmark_gate
from app.services.full_book_evidence import audit_pipeline_sha256
from app.services.gold_corpus import evaluate_corpus_readiness, freeze_manifest

REQUIRED_PRODUCTION_CHECKS = {
    "api_readiness",
    "backup_restore",
    "container_build",
    "database_migration",
    "object_storage",
    "ocr_runtime",
    "worker_readiness",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def evaluate_g6_release_readiness(
    *,
    annotations: list[dict[str, Any]],
    source_metadata: dict[str, Any],
    manifest: dict[str, Any],
    benchmark_report: dict[str, Any],
    full_book_evidence: dict[str, Any],
    production_smoke: dict[str, Any],
    repository_root: str | Path,
    expected_git_sha: str,
) -> dict[str, Any]:
    blockers: list[str] = []
    source_sha = source_metadata.get("document_sha256")
    source_pages = source_metadata.get("pdf_page_count")
    if not isinstance(source_sha, str) or not _SHA256.fullmatch(source_sha):
        blockers.append("source_identity_invalid")
    if not isinstance(source_pages, int) or source_pages <= 0:
        blockers.append("source_page_count_invalid")

    corpus = evaluate_corpus_readiness(annotations)
    if corpus["status"] != "READY_TO_FREEZE":
        blockers.append("gold_corpus_not_human_verified")
    annotation_source_hashes = {item.get("document_sha256") for item in annotations}
    if annotation_source_hashes != {source_sha}:
        blockers.append("gold_source_identity_mismatch")

    expected_manifest = None
    if corpus["status"] == "READY_TO_FREEZE":
        expected_manifest = freeze_manifest(annotations)
        if manifest != expected_manifest:
            blockers.append("frozen_manifest_mismatch")
    else:
        blockers.append("frozen_manifest_unavailable")

    benchmark = evaluate_benchmark_gate(benchmark_report)
    if benchmark["status"] != "PASS":
        blockers.append("gold_regression_failed")
    expected_manifest_hash = (
        expected_manifest.get("manifest_sha256") if expected_manifest else None
    )
    if (
        benchmark_report.get("benchmark_schema_version") != "1.0"
        or benchmark_report.get("dataset_version") != "1.0"
        or benchmark_report.get("status") != "PASS"
        or benchmark_report.get("page_count") != 30
        or benchmark_report.get("failed_samples") != []
        or benchmark_report.get("source_document_sha256") != source_sha
        or benchmark_report.get("gold_manifest_sha256") != expected_manifest_hash
    ):
        blockers.append("gold_regression_evidence_mismatch")

    _evaluate_full_book(
        full_book_evidence,
        annotations=annotations,
        source_sha=source_sha,
        source_pages=source_pages,
        repository_root=repository_root,
        blockers=blockers,
    )
    _evaluate_production_smoke(
        production_smoke,
        expected_git_sha=expected_git_sha,
        blockers=blockers,
    )

    blockers = sorted(set(blockers))
    outstanding_reviews = _outstanding_full_book_reviews(full_book_evidence, annotations)
    return {
        "gate": "G6_PRODUCTION_RELEASE",
        "ruleset_version": "1.0.0",
        "status": "PASS" if not blockers else "FAIL",
        "publish_allowed": not blockers,
        "blocking_failures": blockers,
        "metrics": {
            "gold_annotation_count": corpus["annotation_count"],
            "human_verified_gold_pages": corpus["human_verified_count"],
            "full_book_page_count": full_book_evidence.get("source_page_count", 0),
            "full_book_page_representation_coverage": full_book_evidence.get(
                "page_representation_coverage", 0.0
            ),
            "full_book_entry_candidates": full_book_evidence.get(
                "entry_candidate_count", 0
            ),
            "full_book_parsed_entries": full_book_evidence.get("parsed_entry_count", 0),
            "outstanding_full_book_reviews": len(outstanding_reviews),
            "gold_regression_exact_match": bool(benchmark_report.get("exact_match")),
            "production_checks_passed": len(
                set(production_smoke.get("checks") or []) & REQUIRED_PRODUCTION_CHECKS
            ),
        },
        "evidence": {
            "source_document_sha256": source_sha,
            "gold_manifest_sha256": (
                expected_manifest_hash
            ),
            "private_full_book_audit_sha256": full_book_evidence.get(
                "private_audit_report_sha256"
            ),
            "audit_pipeline_sha256": full_book_evidence.get("audit_pipeline_sha256"),
            "production_image_id": production_smoke.get("image_id"),
            "production_git_sha": production_smoke.get("git_sha"),
            "outstanding_full_book_review_items": outstanding_reviews,
        },
        "component_results": {
            "gold_corpus": corpus,
            "gold_regression": benchmark,
            "full_book_audit_status": full_book_evidence.get("status"),
            "production_smoke_status": production_smoke.get("status"),
        },
    }


def _evaluate_full_book(
    evidence: dict[str, Any],
    *,
    annotations: list[dict[str, Any]],
    source_sha: Any,
    source_pages: Any,
    repository_root: str | Path,
    blockers: list[str],
) -> None:
    if evidence.get("evidence_schema_version") != "1.0":
        blockers.append("full_book_evidence_schema_invalid")
    if evidence.get("source_document_sha256") != source_sha:
        blockers.append("full_book_source_identity_mismatch")
    if evidence.get("source_page_count") != source_pages:
        blockers.append("full_book_page_count_mismatch")
    if evidence.get("page_representation_coverage") != 1.0:
        blockers.append("full_book_page_representation_incomplete")
    if evidence.get("unrepresented_pages") != []:
        blockers.append("full_book_unrepresented_pages")
    if int(evidence.get("source_block_count") or 0) <= 0:
        blockers.append("full_book_source_blocks_missing")
    candidates = int(evidence.get("entry_candidate_count") or 0)
    parsed = int(evidence.get("parsed_entry_count") or 0)
    if candidates <= 0 or parsed != candidates:
        blockers.append("full_book_structured_extraction_incomplete")
    if (
        int(evidence.get("native_text_pages") or 0)
        + int(evidence.get("ocr_text_pages") or 0)
        != source_pages
    ):
        blockers.append("full_book_page_accounting_mismatch")
    queue = evidence.get("review_queue")
    if not isinstance(queue, list) or len(queue) != evidence.get("review_queue_count"):
        blockers.append("full_book_review_queue_invalid")
    expected_audit_status = "REVIEW_REQUIRED" if queue else "PASS"
    if evidence.get("status") != expected_audit_status:
        blockers.append("full_book_audit_status_inconsistent")
    if evidence.get("copyrighted_excerpts_included") is not False:
        blockers.append("copyrighted_source_in_release_evidence")
    private_hash = evidence.get("private_audit_report_sha256")
    if not isinstance(private_hash, str) or not _SHA256.fullmatch(private_hash):
        blockers.append("private_full_book_audit_hash_invalid")
    try:
        expected_pipeline_hash = audit_pipeline_sha256(repository_root)
    except OSError:
        blockers.append("audit_pipeline_files_unavailable")
    else:
        if evidence.get("audit_pipeline_sha256") != expected_pipeline_hash:
            blockers.append("full_book_audit_stale_for_pipeline")
    if _outstanding_full_book_reviews(evidence, annotations):
        blockers.append("full_book_reviews_outstanding")


def _outstanding_full_book_reviews(
    evidence: dict[str, Any], annotations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    verified_pages = {
        int(item["page_number"])
        for item in annotations
        if item.get("review_status") == "HUMAN_VERIFIED"
    }
    queue = evidence.get("review_queue")
    if not isinstance(queue, list):
        return [{"reason": "invalid_review_queue"}]
    return [
        item
        for item in queue
        if not set(item.get("page_numbers") or []).issubset(verified_pages)
    ]


def _evaluate_production_smoke(
    evidence: dict[str, Any], *, expected_git_sha: str, blockers: list[str]
) -> None:
    if evidence.get("evidence_schema_version") != "1.0":
        blockers.append("production_smoke_schema_invalid")
    if evidence.get("status") != "PASS":
        blockers.append("production_smoke_failed")
    checks = set(evidence.get("checks") or [])
    if not REQUIRED_PRODUCTION_CHECKS.issubset(checks):
        blockers.append("production_smoke_checks_incomplete")
    if evidence.get("git_sha") != expected_git_sha:
        blockers.append("production_smoke_stale_for_commit")
    image_id = evidence.get("image_id")
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        blockers.append("production_image_identity_invalid")
