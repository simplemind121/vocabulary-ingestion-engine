from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.services.full_book_evidence import build_redacted_full_book_evidence

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create copyright-safe release evidence from a private full-book audit."
    )
    parser.add_argument("audit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        payload = args.audit.read_bytes()
        report = json.loads(payload)
        if not isinstance(report, dict):
            raise TypeError("full-book audit must be a JSON object")
        evidence = build_redacted_full_book_evidence(
            report,
            report_bytes=payload,
            repository_root=ROOT,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2

    print(
        json.dumps(
            {
                "status": evidence["status"],
                "review_queue_count": evidence["review_queue_count"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
