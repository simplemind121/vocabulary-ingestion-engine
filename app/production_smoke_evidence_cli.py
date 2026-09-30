from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.services.release_readiness import REQUIRED_PRODUCTION_CHECKS


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record production smoke evidence after every check succeeds."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--image-id", required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.git_sha):
        parser.error("git SHA must be a full 40-character lowercase commit hash")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.image_id):
        parser.error("image ID must be a sha256 digest")

    evidence = {
        "evidence_schema_version": "1.0",
        "status": "PASS",
        "git_sha": args.git_sha,
        "image_id": args.image_id,
        "checks": sorted(REQUIRED_PRODUCTION_CHECKS),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
