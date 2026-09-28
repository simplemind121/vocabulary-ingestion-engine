from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.gold_sample_selection import (
    profile_pdf_pages,
    select_gold_sample_candidates,
    summarize_candidate_coverage,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Profile a vocabulary PDF and emit Gold Sample candidate pages."
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--target-pages", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    profiles = profile_pdf_pages(args.pdf)
    candidates = select_gold_sample_candidates(
        profiles,
        target_pages=args.target_pages,
    )
    payload = {
        "selection_schema_version": "1.0",
        "source_pdf": args.pdf.name,
        "target_pages": args.target_pages,
        "coverage": summarize_candidate_coverage(candidates),
        "candidates": candidates,
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is None:
        print(encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
