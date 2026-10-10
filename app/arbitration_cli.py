"""Send a run's parked OCR lines to the configured vision model for arbitration."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.db import SessionLocal
from app.models import ReviewTask, SourceEntry, SourceEntryBlock
from app.services.arbitration import OpenAIChatArbiter, arbitrate_parked_lines
from app.services.ocr_quality import DEFERRED, READERS_DISAGREE
from app.settings import get_settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--limit", type=int, help="arbitrate at most this many lines")
    parser.add_argument("--dry-run", action="store_true", help="count the work, call nothing")
    args = parser.parse_args(argv)
    settings = get_settings()

    with SessionLocal() as db:
        if args.dry_run:
            linked = {
                row.source_block_id
                for row in db.query(SourceEntryBlock.source_block_id)
                .join(SourceEntry, SourceEntry.id == SourceEntryBlock.source_entry_id)
                .filter(SourceEntry.processing_run_id == args.run_id)
            }
            lines = sum(
                task.target_entity_id in linked
                and "machine_arbitration" not in (task.source_context or {})
                for task in db.query(ReviewTask).filter(
                    ReviewTask.processing_run_id == args.run_id,
                    ReviewTask.reason_code == READERS_DISAGREE,
                    ReviewTask.status == DEFERRED,
                )
            )
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
            db, args.run_id, arbiter, batch_size=settings.arbiter_batch_size, limit=args.limit
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
