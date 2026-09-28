from __future__ import annotations

from typing import Any

ANNOTATION_SCHEMA_VERSION = "1.0"


def build_annotation_scaffold(
    *,
    sample_id: str,
    document_sha256: str,
    page_number: int,
    layout_tags: list[str],
) -> dict[str, Any]:
    """Create a deliberately non-verified annotation shell for human review."""
    return {
        "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
        "sample_id": sample_id,
        "document_sha256": document_sha256,
        "page_number": page_number,
        "layout_tags": sorted(set(layout_tags)),
        "review_status": "DRAFT",
        "reviewer_id": None,
        "page_image_sha256": None,
        "blocks": [],
        "entries": [],
        "vocabulary": [],
        "review_notes": [],
    }


def validate_ground_truth_annotation(annotation: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if annotation.get("annotation_schema_version") != ANNOTATION_SCHEMA_VERSION:
        errors.append("annotation_schema_version_must_be_1.0")
    if not _nonempty(annotation.get("sample_id")):
        errors.append("sample_id_required")
    if not _is_sha256(annotation.get("document_sha256")):
        errors.append("document_sha256_invalid")
    if not isinstance(annotation.get("page_number"), int) or annotation["page_number"] < 1:
        errors.append("page_number_invalid")
    if not isinstance(annotation.get("layout_tags"), list) or not annotation["layout_tags"]:
        errors.append("layout_tags_required")

    for field in ("blocks", "entries", "vocabulary"):
        if not isinstance(annotation.get(field), list):
            errors.append(f"{field}_must_be_array")

    if annotation.get("review_status") == "HUMAN_VERIFIED":
        if not _nonempty(annotation.get("reviewer_id")):
            errors.append("reviewer_id_required_for_human_verified")
        if not _is_sha256(annotation.get("page_image_sha256")):
            errors.append("page_image_sha256_required_for_human_verified")
        if not annotation.get("blocks"):
            errors.append("blocks_required_for_human_verified")
        if not annotation.get("entries"):
            errors.append("entries_required_for_human_verified")
        if not annotation.get("vocabulary"):
            errors.append("vocabulary_required_for_human_verified")

    return {
        "status": "PASS" if not errors else "FAIL",
        "review_status": annotation.get("review_status"),
        "errors": errors,
    }


def promote_annotation_to_human_verified(
    annotation: dict[str, Any],
    *,
    reviewer_id: str,
    page_image_sha256: str,
) -> dict[str, Any]:
    """Promote only complete annotations; never manufacture ground truth."""
    promoted = dict(annotation)
    promoted["review_status"] = "HUMAN_VERIFIED"
    promoted["reviewer_id"] = reviewer_id
    promoted["page_image_sha256"] = page_image_sha256
    result = validate_ground_truth_annotation(promoted)
    if result["status"] != "PASS":
        raise ValueError("cannot promote incomplete annotation: " + ",".join(result["errors"]))
    return promoted


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)
