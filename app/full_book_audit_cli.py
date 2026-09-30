from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.services.full_book_audit import audit_full_book
from app.services.ocr_factory import build_ocr_adapter
from app.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a source-bound whole-book extraction audit.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--source-metadata",
        type=Path,
        default=ROOT / "gold_samples" / "source_document.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data-private" / "full-book-native-audit.json",
    )
    parser.add_argument("--ocr-engine", default="tesseract")
    parser.add_argument("--ocr-languages", default="eng+chi_sim")
    parser.add_argument("--ocr-min-confidence", type=float, default=0.85)
    args = parser.parse_args(argv)

    try:
        metadata = json.loads(args.source_metadata.read_text(encoding="utf-8"))
        adapter = build_ocr_adapter(
            Settings(ocr_engine=args.ocr_engine, ocr_languages=args.ocr_languages)
        )
        report = audit_full_book(
            args.pdf,
            expected_sha256=metadata["document_sha256"],
            expected_page_count=int(metadata["pdf_page_count"]),
            ocr_adapter=adapter,
            ocr_min_confidence=args.ocr_min_confidence,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, RuntimeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2

    summary = {key: value for key, value in report.items() if key != "review_queue"}
    summary["output"] = str(args.output)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
