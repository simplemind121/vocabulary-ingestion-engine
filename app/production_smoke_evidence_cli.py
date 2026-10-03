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
    parser.add_argument("--upgrade-from-git-sha", required=True)
    parser.add_argument("--upgrade-from-image-id", required=True)
    parser.add_argument("--recovery-state-sha256", required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.git_sha):
        parser.error("git SHA must be a full 40-character lowercase commit hash")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.image_id):
        parser.error("image ID must be a sha256 digest")
    if not re.fullmatch(r"[0-9a-f]{40}", args.upgrade_from_git_sha):
        parser.error("upgrade source Git SHA must be a full 40-character lowercase commit hash")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.upgrade_from_image_id):
        parser.error("upgrade source image ID must be a sha256 digest")
    if not re.fullmatch(r"[0-9a-f]{64}", args.recovery_state_sha256):
        parser.error("recovery state SHA256 must be a lowercase SHA256 digest")
    if args.git_sha == args.upgrade_from_git_sha or args.image_id == args.upgrade_from_image_id:
        parser.error("upgrade source and release candidate identities must differ")

    evidence = {
        "evidence_schema_version": "1.0",
        "status": "PASS",
        "git_sha": args.git_sha,
        "image_id": args.image_id,
        "upgrade_from_git_sha": args.upgrade_from_git_sha,
        "upgrade_from_image_id": args.upgrade_from_image_id,
        "recovery_state_sha256": args.recovery_state_sha256,
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
