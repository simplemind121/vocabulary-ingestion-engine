from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.gold_annotation_batch import build_annotation_scaffold_batch


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"json_root_must_be_object:{path}")
    return payload


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the frozen 30-page Gold DRAFT scaffold artifact from the "
            "selection plan and deterministic page-image hash registry."
        )
    )
    parser.add_argument("--selection-plan", type=Path, required=True)
    parser.add_argument("--page-hashes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    selection_plan = _load_object(args.selection_plan)
    page_hashes = _load_object(args.page_hashes)
    scaffolds = build_annotation_scaffold_batch(selection_plan, page_hashes)
    _write_json_atomic(args.output, scaffolds)
    print(f"wrote {len(scaffolds)} frozen DRAFT scaffolds to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
