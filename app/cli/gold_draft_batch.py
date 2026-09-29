from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.db import SessionLocal
from app.services.gold_run_batch import build_gold_draft_batch_from_run


def _load_scaffolds(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("scaffolds_json_must_be_a_list")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError("scaffold_items_must_be_objects")
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
            "Build the frozen 30-page machine DRAFT annotation batch from one "
            "persisted ProcessingRun."
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scaffolds", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generator", required=True)
    args = parser.parse_args()

    scaffolds = _load_scaffolds(args.scaffolds)
    with SessionLocal() as db:
        drafts = build_gold_draft_batch_from_run(
            db,
            args.run_id,
            scaffolds,
            generator=args.generator,
        )

    # The service contract is fail-closed; do not leave a partial output file if
    # identity/provenance validation fails before this point.
    _write_json_atomic(args.output, drafts)
    print(f"wrote {len(drafts)} machine DRAFT annotations to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
