from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.gold_annotation import build_annotation_scaffold, validate_ground_truth_annotation
from app.services.gold_sample import REQUIRED_LAYOUT_TAGS


def build_annotation_corpus(plan: dict[str, Any], page_hashes: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = plan.get("candidates", [])
    hashes = page_hashes.get("pages", {})
    if len(candidates) != 30:
        raise ValueError("Gold Sample v1 requires exactly 30 selected pages")
    corpus = []
    for candidate in candidates:
        page = int(candidate["pdf_page"])
        digest = hashes.get(str(page))
        if not digest:
            raise ValueError(f"missing deterministic page image hash for page {page}")
        annotation = build_annotation_scaffold(
            sample_id=f"gold-v1-p{page:04d}",
            document_sha256=plan["source_document_sha256"],
            page_number=page,
            layout_tags=candidate["tags"],
        )
        annotation["page_image_sha256"] = digest
        corpus.append(annotation)
    return corpus


def evaluate_corpus_readiness(annotations: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    if len(annotations) != 30:
        errors.append("annotation_count_must_equal_30")
    covered = {tag for item in annotations for tag in item.get("layout_tags", [])}
    missing = sorted(REQUIRED_LAYOUT_TAGS - covered)
    if missing:
        errors.append("missing_layout_coverage:" + ",".join(missing))
    verified = 0
    for annotation in annotations:
        result = validate_ground_truth_annotation(annotation)
        if result["status"] != "PASS":
            errors.extend(f"{annotation.get('sample_id')}:{error}" for error in result["errors"])
        if annotation.get("review_status") == "HUMAN_VERIFIED" and result["status"] == "PASS":
            verified += 1
    if verified != 30:
        errors.append(f"human_verified_count_must_equal_30:{verified}")
    return {
        "status": "READY_TO_FREEZE" if not errors else "NOT_READY",
        "annotation_count": len(annotations),
        "human_verified_count": verified,
        "covered_layout_tags": sorted(covered),
        "missing_layout_tags": missing,
        "errors": errors,
    }


def freeze_manifest(annotations: list[dict[str, Any]]) -> dict[str, Any]:
    readiness = evaluate_corpus_readiness(annotations)
    if readiness["status"] != "READY_TO_FREEZE":
        raise ValueError("Gold corpus cannot freeze: " + ";".join(readiness["errors"]))
    pages = []
    for annotation in sorted(annotations, key=lambda item: item["page_number"]):
        payload = json.dumps(annotation, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        pages.append(
            {
                "sample_id": annotation["sample_id"],
                "document_sha256": annotation["document_sha256"],
                "page_number": annotation["page_number"],
                "page_image_sha256": annotation["page_image_sha256"],
                "layout_tags": annotation["layout_tags"],
                "ground_truth_path": f"annotations/{annotation['sample_id']}.json",
                "ground_truth_sha256": hashlib.sha256(payload).hexdigest(),
                "review_status": "HUMAN_VERIFIED",
                "reviewer_id": annotation["reviewer_id"],
                "annotation_schema_version": annotation["annotation_schema_version"],
            }
        )
    manifest = {"dataset_version": "1.0", "freeze_status": "FROZEN", "pages": pages}
    manifest_payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    manifest["manifest_sha256"] = hashlib.sha256(manifest_payload).hexdigest()
    return manifest


def write_annotation_scaffolds(annotations: list[dict[str, Any]], root: str | Path) -> list[Path]:
    target = Path(root)
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for annotation in annotations:
        path = target / f"{annotation['sample_id']}.json"
        path.write_text(json.dumps(annotation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written
