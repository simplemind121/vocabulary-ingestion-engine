from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db import SessionLocal
from app.services.gold_annotation_batch import build_annotation_scaffold_batch
from app.services.gold_native_preannotation import build_native_pdf_predictions
from app.services.gold_page_hashes import GOLD_RENDER_CONTRACT
from app.services.gold_preannotation_batch import build_machine_annotation_batch
from app.services.gold_review_packet import build_page_predictions, write_review_packet

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a private 30-page source-vs-machine Gold review packet."
    )
    parser.add_argument(
        "run_id",
        nargs="?",
        help="Persisted processing run containing all selected pages",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        help="Confirmed source PDF; runs the production native adapter without DB ingestion",
    )
    parser.add_argument(
        "--selection-plan",
        type=Path,
        default=ROOT / "gold_samples" / "selection_plan_v1.json",
    )
    parser.add_argument(
        "--page-hashes",
        type=Path,
        default=ROOT / "gold_samples" / "page_image_hashes_v1.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data-private" / "gold-review-packet-v1",
    )
    parser.add_argument("--generator", default="vie-pipeline@0.1.0-alpha.4")
    args = parser.parse_args()
    if bool(args.run_id) == bool(args.pdf):
        parser.error("provide exactly one of run_id or --pdf")

    selection = json.loads(args.selection_plan.read_text(encoding="utf-8"))
    hashes = json.loads(args.page_hashes.read_text(encoding="utf-8"))
    scaffolds = build_annotation_scaffold_batch(selection, hashes)

    if args.pdf:
        predictions, image_paths = build_native_pdf_predictions(
            args.pdf,
            scaffolds,
            args.output.parent / "gold-source-pages-v1",
        )
        generator = f"pymupdf-native@{GOLD_RENDER_CONTRACT['engine_version']}"
    else:
        db = SessionLocal()
        try:
            predictions, image_paths = build_page_predictions(db, args.run_id, scaffolds)
        finally:
            db.close()
        generator = args.generator
    drafts = build_machine_annotation_batch(
        scaffolds,
        predictions,
        generator=generator,
    )
    packet = write_review_packet(drafts, image_paths, args.output)
    print(
        json.dumps(
            {
                "status": "DRAFT_REVIEW_PACKET_READY",
                "page_count": packet["page_count"],
                "human_verified_count": packet["human_verified_count"],
                "index": str(args.output / "index.html"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
