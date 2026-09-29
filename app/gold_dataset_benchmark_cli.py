from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.services.benchmark import run_gold_benchmark
from app.services.gold_corpus import evaluate_corpus_readiness


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark real machine predictions against verified Gold annotations."
    )
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        truth = _load_by_sample_id(args.annotations)
        predictions = _load_by_sample_id(args.predictions)
        readiness = evaluate_corpus_readiness(list(truth.values()))
        if readiness["status"] != "READY_TO_FREEZE":
            raise ValueError("Gold annotations are not ready to freeze")
        if set(truth) != set(predictions):
            raise ValueError("prediction sample IDs must exactly match verified annotations")

        page_reports = []
        for sample_id in sorted(truth):
            annotation = truth[sample_id]
            prediction = predictions[sample_id]
            _require_prediction_identity(annotation, prediction)
            page_reports.append(
                {
                    "sample_id": sample_id,
                    "page_number": annotation["page_number"],
                    **run_gold_benchmark(prediction, annotation),
                }
            )
        report = _aggregate(page_reports)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


def _load_by_sample_id(directory: Path) -> dict[str, dict[str, Any]]:
    if not directory.is_dir():
        raise ValueError(f"directory unavailable: {directory}")
    result = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("sample_id"), str):
            raise TypeError(f"sample_id missing from {path}")
        sample_id = payload["sample_id"]
        if sample_id in result:
            raise ValueError(f"duplicate sample_id: {sample_id}")
        result[sample_id] = payload
    return result


def _require_prediction_identity(annotation: dict, prediction: dict) -> None:
    for field in ("sample_id", "document_sha256", "page_number", "page_image_sha256"):
        if prediction.get(field) != annotation.get(field):
            raise ValueError(f"prediction identity mismatch: {annotation['sample_id']}:{field}")


def _aggregate(page_reports: list[dict[str, Any]]) -> dict[str, Any]:
    if len(page_reports) != 30:
        raise ValueError("Gold benchmark requires exactly 30 page reports")
    exact = all(page["exact_match"] for page in page_reports)
    return {
        "benchmark_schema_version": "1.0",
        "dataset_version": "1.0",
        "page_count": len(page_reports),
        "status": "PASS" if exact else "FAIL",
        "exact_match": exact,
        "layers": {
            "ocr": {"f1": min(page["layers"]["ocr"]["f1"] for page in page_reports)},
            "segmentation": {
                "f1": min(page["layers"]["segmentation"]["f1"] for page in page_reports)
            },
            "canonical": {
                "field_accuracy": min(
                    page["layers"]["canonical"]["field_accuracy"] for page in page_reports
                )
            },
        },
        "failed_samples": [
            page["sample_id"] for page in page_reports if not page["exact_match"]
        ],
        "pages": page_reports,
    }


if __name__ == "__main__":
    sys.exit(main())
