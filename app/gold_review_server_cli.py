from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from app.gold_review_server import create_gold_review_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the private Gold Sample human review UI.")
    parser.add_argument(
        "--packet",
        type=Path,
        default=Path("data-private/gold-review-packet-v1"),
    )
    parser.add_argument(
        "--annotations",
        type=Path,
        default=Path("gold_samples/annotations"),
    )
    parser.add_argument(
        "--media-packet",
        type=Path,
        default=Path("data-private/gold-media-review-packet-v1"),
    )
    parser.add_argument(
        "--media-annotations",
        type=Path,
        default=Path("gold_samples/media_annotations"),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Gold review contains copyrighted page images and must bind to localhost")
    has_media = (args.media_packet / "packet.json").exists()
    app = create_gold_review_app(
        args.packet,
        args.annotations,
        media_packet_dir=args.media_packet if has_media else None,
        media_annotations_dir=args.media_annotations if has_media else None,
    )
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
