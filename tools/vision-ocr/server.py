#!/usr/bin/env python3
"""Serve macOS Vision text recognition to the ingestion worker.

Vision ships with macOS and cannot run in a container, so the worker posts a
page image here and receives text rows with normalized boxes. Standard library
only. Build the reader once, then run this on the Mac:

    swiftc -O tools/vision-ocr/ocr.swift -o tools/vision-ocr/ocr
    python3 tools/vision-ocr/server.py --port 8791

and point the worker at it with VIE_VISION_OCR_URL=http://host.docker.internal:8791/ocr
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

READER = Path(__file__).with_name("ocr")
MAX_BYTES = 64 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send(200 if READER.exists() else 503, {"status": "ok", "reader": READER.exists()})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if self.path != "/ocr" or not 0 < length <= MAX_BYTES:
            self._send(400, {"detail": "POST a PNG to /ocr"})
            return
        with tempfile.NamedTemporaryFile(suffix=".png") as image:
            image.write(self.rfile.read(length))
            image.flush()
            done = subprocess.run(
                [str(READER), image.name], capture_output=True, text=True, timeout=120, check=False
            )
        if done.returncode != 0 or not done.stdout.strip():
            self._send(502, {"detail": done.stderr.strip() or "Vision reader produced no output"})
            return
        self._send(200, {"rows": json.loads(done.stdout.splitlines()[0])["rows"]})

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()
    if not READER.exists():
        parser.error(f"build the reader first: swiftc -O {READER}.swift -o {READER}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
