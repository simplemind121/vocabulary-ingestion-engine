from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.services.release_readiness import evaluate_g6_release_readiness

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the fail-closed G6 release Gate.")
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--source-metadata", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--full-book-evidence", type=Path, required=True)
    parser.add_argument("--production-smoke", type=Path, required=True)
    parser.add_argument("--media-annotations", type=Path, required=True)
    parser.add_argument("--media-predictions", type=Path, required=True)
    parser.add_argument("--source-media-evidence", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = evaluate_g6_release_readiness(
            annotations=_load_annotations(args.annotations),
            source_metadata=_load_object(args.source_metadata),
            manifest=_load_object(args.manifest),
            benchmark_report=_load_object(args.benchmark),
            full_book_evidence=_load_object(args.full_book_evidence),
            production_smoke=_load_object(args.production_smoke),
            media_annotations=_load_annotations(args.media_annotations),
            media_predictions=_load_annotations(args.media_predictions),
            source_media_evidence=_load_object(args.source_media_evidence),
            repository_root=ROOT,
            expected_git_sha=args.git_sha,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"gate": "G6_PRODUCTION_RELEASE", "status": "ERROR", "error": str(exc)}))
        return 2

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if args.require_pass and result["status"] != "PASS" else 0


def _load_annotations(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        raise ValueError(f"annotation directory unavailable: {directory}")
    return [_load_object(path) for path in sorted(directory.glob("*.json"))]


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON object required: {path}")
    return payload


if __name__ == "__main__":
    sys.exit(main())
