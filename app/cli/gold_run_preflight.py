from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.db import SessionLocal
from app.services.gold_run_preflight import inspect_gold_run_candidates


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path}: expected JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect persisted ProcessingRuns against the frozen Gold sample."
    )
    parser.add_argument(
        "--selection-plan",
        type=Path,
        default=Path("gold_samples/selection_plan_v1.json"),
    )
    parser.add_argument(
        "--page-hashes",
        type=Path,
        default=Path("gold_samples/page_image_hashes_v1.json"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    selection = _load_object(args.selection_plan)
    hashes = _load_object(args.page_hashes)
    document_sha256 = selection.get("source_document_sha256")
    if not isinstance(document_sha256, str) or not document_sha256:
        raise ValueError("selection_plan_missing_source_document_sha256")
    if hashes.get("source_document_sha256") != document_sha256:
        raise ValueError("gold_asset_document_sha256_mismatch")

    candidates = selection.get("candidates")
    page_hashes = hashes.get("pages")
    if not isinstance(candidates, list) or not isinstance(page_hashes, dict):
        raise TypeError("invalid_gold_asset_shape")
    page_numbers = [int(item["pdf_page"]) for item in candidates]
    expected_hashes = {int(page): str(sha) for page, sha in page_hashes.items()}
    if len(page_numbers) != 30 or len(set(page_numbers)) != 30:
        raise ValueError("gold_selection_must_contain_exactly_30_unique_pages")
    if set(page_numbers) != set(expected_hashes):
        raise ValueError("gold_selection_and_page_hash_registry_mismatch")

    with SessionLocal() as db:
        runs = inspect_gold_run_candidates(
            db,
            document_sha256=document_sha256,
            page_numbers=page_numbers,
            page_image_sha256=expected_hashes,
        )

    payload = {
        "source_document_sha256": document_sha256,
        "frozen_page_count": len(page_numbers),
        "candidate_run_count": len(runs),
        "ready_run_ids": [
            item["processing_run_id"]
            for item in runs
            if item["ready_for_gold_draft"]
        ],
        "runs": runs,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(f".{args.output.name}.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    print(rendered, end="")
    return 0 if payload["ready_run_ids"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
