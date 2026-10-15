"""Mark a run's entries for rebuilding on its next pass.

Use after upgrading the pipeline, or after corrections made to a run whose
entries were cut before corrections were tracked. Nothing is deleted here:
the next pipeline pass rebuilds the entries, and refuses if that would discard
a human-verified entry or media association.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.db import SessionLocal
from app.models import ProcessingStep


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_id")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        step = (
            db.query(ProcessingStep)
            .filter(
                ProcessingStep.processing_run_id == args.run_id,
                ProcessingStep.sequence_no == 20,
            )
            .one_or_none()
        )
        if step is None:
            print(json.dumps({"run_id": args.run_id, "marked": False, "reason": "not segmented yet"}))
            return 1
        step.metrics = {**(step.metrics or {}), "blocks_fingerprint": "stale"}
        db.commit()
    print(json.dumps({"run_id": args.run_id, "marked": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
