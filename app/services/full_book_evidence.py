from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

AUDIT_PIPELINE_FILES = (
    "app/adapters/pdf_native.py",
    "app/adapters/tesseract.py",
    "app/services/full_book_audit.py",
    "app/services/gold_sample_selection.py",
    "app/services/segmentation.py",
    "app/services/structured_extraction.py",
)


def audit_pipeline_sha256(repository_root: str | Path) -> str:
    root = Path(repository_root)
    digest = hashlib.sha256()
    for relative in AUDIT_PIPELINE_FILES:
        payload = (root / relative).read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def build_redacted_full_book_evidence(
    report: dict[str, Any],
    *,
    report_bytes: bytes,
    repository_root: str | Path,
) -> dict[str, Any]:
    required = (
        "audit_schema_version",
        "status",
        "source_document_sha256",
        "source_page_count",
        "native_text_pages",
        "ocr_engine",
        "ocr_pages_attempted",
        "ocr_text_pages",
        "page_representation_coverage",
        "unrepresented_pages",
        "source_block_count",
        "ocr_source_block_count",
        "low_confidence_ocr_block_count",
        "entry_candidate_count",
        "parsed_entry_count",
        "cross_page_entry_count",
        "review_queue_count",
    )
    missing = [field for field in required if field not in report]
    if missing:
        raise ValueError("full-book audit is missing fields: " + ",".join(missing))
    queue = report.get("review_queue")
    if not isinstance(queue, list) or len(queue) != int(report["review_queue_count"]):
        raise ValueError("full-book audit review queue count mismatch")

    redacted_queue = []
    for item in queue:
        pages = item.get("page_numbers")
        reasons = item.get("reasons")
        if (
            not isinstance(pages, list)
            or not pages
            or not all(isinstance(page, int) and page > 0 for page in pages)
            or not isinstance(reasons, list)
            or not reasons
            or not all(isinstance(reason, str) and reason for reason in reasons)
        ):
            raise ValueError("full-book audit contains an invalid review item")
        sanitized = {"page_numbers": pages, "reasons": reasons}
        if item.get("source_block_id") is not None:
            sanitized["source_block_id"] = str(item["source_block_id"])
        if item.get("confidence") is not None:
            sanitized["confidence"] = float(item["confidence"])
        redacted_queue.append(sanitized)

    return {
        "evidence_schema_version": "1.0",
        "audit_pipeline_sha256": audit_pipeline_sha256(repository_root),
        "private_audit_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        **{field: report[field] for field in required},
        "review_queue": redacted_queue,
        "copyrighted_excerpts_included": False,
    }


def validate_redacted_full_book_evidence(
    evidence: dict[str, Any],
    *,
    source_metadata: dict[str, Any],
    repository_root: str | Path,
) -> dict[str, Any]:
    errors = []
    if evidence.get("evidence_schema_version") != "1.0":
        errors.append("evidence_schema_version_must_be_1.0")
    if evidence.get("source_document_sha256") != source_metadata.get("document_sha256"):
        errors.append("source_document_sha256_mismatch")
    if evidence.get("source_page_count") != source_metadata.get("pdf_page_count"):
        errors.append("source_page_count_mismatch")
    if evidence.get("audit_pipeline_sha256") != audit_pipeline_sha256(repository_root):
        errors.append("audit_pipeline_sha256_mismatch")
    private_hash = evidence.get("private_audit_report_sha256")
    if (
        not isinstance(private_hash, str)
        or len(private_hash) != 64
        or any(character not in "0123456789abcdef" for character in private_hash)
    ):
        errors.append("private_audit_report_sha256_invalid")
    queue = evidence.get("review_queue")
    if not isinstance(queue, list) or len(queue) != evidence.get("review_queue_count"):
        errors.append("review_queue_count_mismatch")
    if evidence.get("copyrighted_excerpts_included") is not False:
        errors.append("copyrighted_excerpts_must_not_be_included")
    if isinstance(queue, list) and any(
        "raw_text_excerpt" in item or "raw_text" in item for item in queue
    ):
        errors.append("copyrighted_review_excerpt_present")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}
