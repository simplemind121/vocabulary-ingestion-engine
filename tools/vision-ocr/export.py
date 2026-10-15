#!/usr/bin/env python3
"""Read a whole PDF with macOS Vision and write the readings as files.

Run on a Mac, then copy the output directory to the server and point the
worker at it with VIE_OCR_READINGS_ROOT and the `vision-import` reader:

    python3 tools/vision-ocr/export.py book.pdf readings/

Requires PyMuPDF (already a project dependency) and the compiled reader.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import fitz

READER = Path(__file__).with_name("ocr")
NAME = "macos-vision"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()
    if not READER.exists():
        parser.error(f"build the reader first: swiftc -O {READER}.swift -o {READER}")
    sha256 = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
    target = args.output / sha256 / NAME
    target.mkdir(parents=True, exist_ok=True)
    document = fitz.open(args.pdf)
    written = 0
    with tempfile.TemporaryDirectory() as scratch:
        for index, page in enumerate(document, start=1):
            destination = target / f"p{index:04d}.json"
            if destination.exists():
                continue
            image = Path(scratch) / "page.png"
            page.get_pixmap(dpi=args.dpi, alpha=False).save(image)
            done = subprocess.run(
                [str(READER), str(image)], capture_output=True, text=True, timeout=300, check=True
            )
            rows = json.loads(done.stdout.splitlines()[0])["rows"]
            destination.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            written += 1
    print(json.dumps({"document_sha256": sha256, "pages": document.page_count, "written": written}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
