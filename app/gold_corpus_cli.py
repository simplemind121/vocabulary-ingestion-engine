from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.services.gold_corpus import evaluate_corpus_readiness, freeze_manifest
from app.services.gold_media import evaluate_media_readiness


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the real Gold annotation corpus.")
    parser.add_argument(
        "--annotations",
        type=Path,
        default=Path("gold_samples/annotations"),
    )
    parser.add_argument(
        "--media-annotations",
        type=Path,
        default=Path("gold_samples/media_annotations"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest-out", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)

    try:
        annotations = _load_annotations(args.annotations)
        result = evaluate_corpus_readiness(annotations)
        media_annotations = _load_annotations(args.media_annotations)
        media = evaluate_media_readiness(annotations, media_annotations)
        result["source_media"] = media
        if media["status"] != "READY_TO_FREEZE":
            # Text Gold alone is no longer complete Source Fidelity Gold.
            result["text_status"] = result["status"]
            result["status"] = "NOT_READY"
            result["errors"] = [*result["errors"], "source_media_gold_not_ready"]
        if args.manifest_out is not None and result["status"] == "READY_TO_FREEZE":
            manifest = freeze_manifest(annotations, media_annotations)
            args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
            args.manifest_out.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result["manifest_path"] = str(args.manifest_out)
            result["manifest_sha256"] = manifest["manifest_sha256"]
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        result = {
            "gate": "GOLD_CORPUS_READINESS",
            "status": "ERROR",
            "publish_allowed": False,
            "error": str(exc),
        }
        _emit(result, args.output)
        return 2

    result["gate"] = "GOLD_CORPUS_READINESS"
    result["publish_allowed"] = result["status"] == "READY_TO_FREEZE"
    _emit(result, args.output)
    if args.require_ready and not result["publish_allowed"]:
        return 1
    return 0


def _load_annotations(directory: Path) -> list[dict]:
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise ValueError("annotations path must be a directory")
    annotations = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError(f"annotation must be an object: {path}")
        annotations.append(payload)
    return annotations


def _emit(result: dict, output: Path | None) -> None:
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    sys.exit(main())
