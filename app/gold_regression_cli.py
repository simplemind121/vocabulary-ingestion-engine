from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from app.services.benchmark_gate import evaluate_benchmark_gate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a Vocabulary Ingestion Engine Gold benchmark report."
    )
    parser.add_argument("report", type=Path, help="Path to benchmark-report.json")
    args = parser.parse_args(argv)

    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("benchmark report must be a JSON object")
        result = evaluate_benchmark_gate(report)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "gate": "GOLD_REGRESSION",
                    "status": "ERROR",
                    "publish_allowed": False,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
