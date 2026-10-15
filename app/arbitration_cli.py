"""Send a run's parked OCR lines to the configured vision model for arbitration."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.db import SessionLocal
from app.services.arbitration import OpenAIChatArbiter, arbitrate_parked_lines, parked_lines
from app.settings import get_settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--limit", type=int, help="arbitrate at most this many lines")
    parser.add_argument("--dry-run", action="store_true", help="count the work, call nothing")
    parser.add_argument(
        "--every-line", action="store_true", help="also lines outside any entry (whole-text books)"
    )
    args = parser.parse_args(argv)
    settings = get_settings()

    with SessionLocal() as db:
        if args.dry_run:
            lines = len(parked_lines(db, args.run_id, every_line=args.every_line))
            if args.limit is not None:
                lines = min(lines, args.limit)
            batch = settings.arbiter_batch_size
            print(json.dumps({"lines": lines, "requests": -(-lines // batch), "batch_size": batch}))
            return 0
        if settings.arbiter_api_key is None or not settings.arbiter_model:
            print(json.dumps({"error": "set VIE_ARBITER_API_KEY and VIE_ARBITER_MODEL"}))
            return 2
        arbiter = OpenAIChatArbiter(
            api_key=settings.arbiter_api_key.get_secret_value(),
            model=settings.arbiter_model,
            base_url=settings.arbiter_base_url,
        )
        result = arbitrate_parked_lines(
            db,
            args.run_id,
            arbiter,
            batch_size=settings.arbiter_batch_size,
            limit=args.limit,
            every_line=args.every_line,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
