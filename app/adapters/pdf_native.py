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
                    metadata={"source": "native_pdf_text"},
                )
            )
        return blocks
