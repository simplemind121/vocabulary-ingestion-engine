"""Evaluate the Gold Source Media Fidelity Gate (no database required)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.services.gold_media import evaluate_media_regression, load_json_directory


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=Path("gold_samples/annotations"))
    parser.add_argument(
        "--media-annotations", type=Path, default=Path("gold_samples/media_annotations")
    )
    parser.add_argument(
        "--media-predictions",
        type=Path,
        default=Path("benchmarks/gold_sample_v1/media_predictions"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = evaluate_media_regression(
            load_json_directory(args.annotations),
            load_json_directory(args.media_annotations),
            load_json_directory(args.media_predictions),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        report = {"gate": "GOLD_SOURCE_MEDIA_FIDELITY", "status": "ERROR", "error": str(exc)}
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 1 if args.require_pass and report["status"] != "PASS" else 0


if __name__ == "__main__":
    sys.exit(main())
