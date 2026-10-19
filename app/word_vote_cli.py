"""Settle a run's disputed lines by their words before paying an arbiter for them.

  python -m app.word_vote_cli RUN --lexicon /path/ecdict.csv [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys

from app.db import SessionLocal
from app.services.word_vote import load_lexicon, settle_parked_lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run")
    parser.add_argument("--lexicon", required=True, help="ECDICT CSV")
    parser.add_argument("--dry-run", action="store_true", help="count, change nothing")
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        print(json.dumps(settle_parked_lines(db, args.run, load_lexicon(args.lexicon), dry_run=args.dry_run)))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
