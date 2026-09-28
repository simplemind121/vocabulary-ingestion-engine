from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED_LAYOUT_TAGS = {
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
}


def load_gold_sample_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid Gold Sample manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Gold Sample manifest root must be an object")
    return data


def validate_gold_sample_manifest(
    manifest: dict[str, Any],
    *,
    root: str | Path | None = None,
    require_files: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    pages = manifest.get("pages")
    if manifest.get("dataset_version") != "1.0":
        errors.append("dataset_version_must_be_1.0")
    if not isinstance(pages, list):
        pages = []
        errors.append("pages_must_be_array")
    if len(pages) != 30:
        errors.append("page_count_must_equal_30")

    seen_ids: set[str] = set()
    covered: set[str] = set()
    root_path = Path(root) if root is not None else None

    for index, page in enumerate(pages, start=1):
        prefix = f"page[{index}]"
        if not isinstance(page, dict):
            errors.append(f"{prefix}:must_be_object")
            continue
        sample_id = page.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id.strip():
            errors.append(f"{prefix}:sample_id_required")
        elif sample_id in seen_ids:
            errors.append(f"{prefix}:duplicate_sample_id")
        else:
            seen_ids.add(sample_id)

        for field in ("document_sha256", "page_image_sha256"):
            value = page.get(field)
            if not _is_sha256(value):
                errors.append(f"{prefix}:{field}_invalid")
        if not isinstance(page.get("page_number"), int) or page["page_number"] < 1:
            errors.append(f"{prefix}:page_number_invalid")
        if page.get("review_status") != "HUMAN_VERIFIED":
            errors.append(f"{prefix}:review_status_not_human_verified")
        for field in ("reviewer_id", "annotation_schema_version", "ground_truth_path"):
            value = page.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}:{field}_required")

        tags = page.get("layout_tags")
        if not isinstance(tags, list) or not tags:
            errors.append(f"{prefix}:layout_tags_required")
        else:
            unknown = set(tags) - REQUIRED_LAYOUT_TAGS
            if unknown:
                errors.append(f"{prefix}:unknown_layout_tags:{','.join(sorted(unknown))}")
            covered.update(set(tags) & REQUIRED_LAYOUT_TAGS)

        if require_files and root_path is not None and isinstance(page.get("ground_truth_path"), str):
            ground_truth = root_path / page["ground_truth_path"]
            if not ground_truth.is_file():
                errors.append(f"{prefix}:ground_truth_file_missing")

    missing_tags = sorted(REQUIRED_LAYOUT_TAGS - covered)
    if missing_tags:
        errors.append(f"missing_required_layout_coverage:{','.join(missing_tags)}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "dataset_version": manifest.get("dataset_version"),
        "page_count": len(pages),
        "human_verified_pages": sum(
            1 for page in pages if isinstance(page, dict) and page.get("review_status") == "HUMAN_VERIFIED"
        ),
        "covered_layout_tags": sorted(covered),
        "missing_layout_tags": missing_tags,
        "errors": errors,
    }


def ground_truth_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)
