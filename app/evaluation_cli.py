"""Measure each OCR reader against Gold pages (hand-checked structured pages).

  python -m app.evaluation_cli readers --lines lines.json --gold pages/ [--out report.json]
  python -m app.evaluation_cli readers --run R --gold pages/

Prints, per reader and split (dev / held-out test), word precision, recall and F1
(order-free), CER and WER in the reader's order, and CER with its lines put in the
Gold page's order; then the median CER per kind of page.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.evaluation.readers import evaluate
from app.structure.evidence import load_lines, run_lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    readers = sub.add_parser("readers")
    readers.add_argument("--run")
    readers.add_argument("--lines")
    readers.add_argument("--gold", required=True, help="directory of pNNN.json Gold pages")
    readers.add_argument("--out", help="write the full report (with per-page scores) as JSON")
    args = parser.parse_args(argv)

    if args.run:
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            lines = run_lines(db, args.run)
        finally:
            db.close()
    elif args.lines:
        lines = load_lines(args.lines)
    else:
        raise SystemExit("give --run or --lines")
    gold = {int(p.stem[1:]): json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(args.gold).glob("p*.json"))}
    report = evaluate(lines, gold)
    print(f"{'reader':<16} {'split':<5} {'pages':>5} {'P':>7} {'R':>7} {'F1':>7} {'CER':>7} {'WER':>7} {'CER*':>7}")
    for name, splits in report["readers"].items():
        for split, s in splits.items():
            print(f"{name:<16} {split:<5} {s['pages']:>5} {s['word_precision']:>7.4f} {s['word_recall']:>7.4f} {s['word_f1']:>7.4f}"
                  f" {s['cer']:>7.4f} {s['wer']:>7.4f} {s['cer_in_gold_order']:>7.4f}")
    print("CER* = CER with the reader's lines in the Gold page's order.")
    for name, kinds in report["by_kind"].items():
        print(name, ", ".join(f"{kind}: median CER {v['median_cer']:.3f} ({v['pages']} pages)" for kind, v in kinds.items()))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
