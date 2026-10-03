from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.services.full_book_evidence import validate_redacted_full_book_evidence

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate committed full-book release evidence.")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--source-metadata", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
        source_metadata = json.loads(args.source_metadata.read_text(encoding="utf-8"))
        if not isinstance(evidence, dict) or not isinstance(source_metadata, dict):
            raise TypeError("evidence and source metadata must be JSON objects")
        result = validate_redacted_full_book_evidence(
            evidence,
            source_metadata=source_metadata,
            repository_root=ROOT,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
