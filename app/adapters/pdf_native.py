from __future__ import annotations

import fitz

from app.idr import BoundingBox, TextBlock


class PyMuPDFNativeAdapter:
    name = "pymupdf-native"
    version = fitz.VersionBind

    def extract_page(self, page: fitz.Page) -> list[TextBlock]:
        width = float(page.rect.width) or 1.0
        height = float(page.rect.height) or 1.0
        blocks: list[TextBlock] = []

        bold_lines = _bold_lines(page)
        raw_blocks = page.get_text("blocks")
        for order, raw in enumerate(raw_blocks):
            x0, y0, x1, y1, text, *_ = raw
            text = str(text).strip()
            if not text:
                continue
            blocks.append(
                TextBlock(
                    text=text,
                    bbox=BoundingBox(
                        x1=max(0.0, min(1.0, float(x0) / width)),
                        y1=max(0.0, min(1.0, float(y0) / height)),
                        x2=max(0.0, min(1.0, float(x1) / width)),
                        y2=max(0.0, min(1.0, float(y1) / height)),
                    ),
                    reading_order=order,
                    confidence=1.0,
                    metadata=_block_metadata(text, bold_lines),
                )
            )
        return blocks


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _bold_lines(page: fitz.Page) -> set[str]:
    """Normalized text of every line typeset entirely in a bold face."""
    lines: set[str] = set()
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            if spans and all(
                "bold" in str(span.get("font", "")).lower() or int(span.get("flags", 0)) & 16
                for span in spans
            ):
                lines.add(_normalize("".join(span["text"] for span in line["spans"])))
    return lines


def _block_metadata(text: str, bold_lines: set[str]) -> dict:
    metadata: dict = {"source": "native_pdf_text"}
    bold = [line for line in map(_normalize, text.splitlines()) if line and line in bold_lines]
    if bold:
        metadata["bold_lines"] = bold
    return metadata
