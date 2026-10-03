from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.gold_annotation import validate_ground_truth_annotation
from app.services.gold_sample import validate_gold_sample_manifest


def assemble_gold_sample_manifest(
    annotations: list[dict[str, Any]],
    *,
    ground_truth_paths: dict[str, str],
) -> dict[str, Any]:
    """Assemble a v1 manifest without weakening HUMAN_VERIFIED requirements."""
    pages: list[dict[str, Any]] = []
    for annotation in annotations:
        result = validate_ground_truth_annotation(annotation)
        if result["status"] != "PASS" or annotation.get("review_status") != "HUMAN_VERIFIED":
            sample_id = annotation.get("sample_id", "<unknown>")
            raise ValueError(f"annotation is not verified ground truth: {sample_id}")
        sample_id = str(annotation["sample_id"])
        ground_truth_path = ground_truth_paths.get(sample_id)
        if not isinstance(ground_truth_path, str) or not ground_truth_path.strip():
            raise ValueError(f"ground truth path missing: {sample_id}")
        pages.append(
            {
                "sample_id": sample_id,
                "document_sha256": annotation["document_sha256"],
                "page_number": annotation["page_number"],
                "page_image_sha256": annotation["page_image_sha256"],
                "layout_tags": annotation["layout_tags"],
                "review_status": annotation["review_status"],
                "reviewer_id": annotation["reviewer_id"],
                "annotation_schema_version": annotation["annotation_schema_version"],
                "ground_truth_path": ground_truth_path,
            }
        )
    return {"dataset_version": "1.0", "pages": sorted(pages, key=lambda page: page["page_number"])}


def assemble_and_validate_gold_sample_manifest(
    annotations: list[dict[str, Any]],
    *,
    ground_truth_paths: dict[str, str],
    root: str | Path | None = None,
    require_files: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = assemble_gold_sample_manifest(
        annotations,
        ground_truth_paths=ground_truth_paths,
    )
    validation = validate_gold_sample_manifest(
        manifest,
        root=root,
        require_files=require_files,
    )
    return manifest, validation
