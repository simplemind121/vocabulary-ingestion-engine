from __future__ import annotations

import io
from typing import Any

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.idr import BoundingBox, TextBlock


class PaddleOcrAdapter:
    """Optional PaddleOCR adapter isolated behind the stable OCR contract.

    PaddleOCR is imported lazily so the base API remains lightweight and can be
    deployed without OCR dependencies. Production OCR images can install the
    dedicated OCR extra and select this adapter through configuration.
    """

    name = "paddleocr"

    def __init__(self, engine: Any | None = None) -> None:
        if engine is None:
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise RuntimeError(
                    "PaddleOCR is not installed; install the OCR runtime before selecting paddleocr"
                ) from exc
            engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        self._engine = engine
        self.version = _package_version("paddleocr")

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        try:
            from PIL import Image
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("PaddleOCR adapter requires Pillow and numpy") from exc

        image = Image.open(io.BytesIO(page.image_bytes)).convert("RGB")
        width, height = image.size
        raw = self._engine.ocr(np.asarray(image), cls=True)
        blocks: list[TextBlock] = []

        # PaddleOCR classic API returns one list of [polygon, (text, score)]
        # records per input image. Keep normalization here so no Paddle-specific
        # shape escapes into the canonical IDR.
        records = raw[0] if raw and isinstance(raw, list) else []
        for order, record in enumerate(records or []):
            if not record or len(record) < 2:
                continue
            polygon, recognition = record[0], record[1]
            if not recognition or len(recognition) < 2:
                continue
            text, confidence = str(recognition[0]).strip(), float(recognition[1])
            if not text:
                continue
            xs = [float(point[0]) for point in polygon]
            ys = [float(point[1]) for point in polygon]
            blocks.append(
                TextBlock(
                    text=text,
                    bbox=BoundingBox(
                        x1=max(min(xs) / width, 0.0),
                        y1=max(min(ys) / height, 0.0),
                        x2=min(max(xs) / width, 1.0),
                        y2=min(max(ys) / height, 1.0),
                    ),
                    reading_order=order,
                    confidence=confidence,
                    block_type="TEXT",
                    metadata={"ocr_engine": self.name},
                )
            )

        return OcrPageResult(
            page_number=page.page_number,
            blocks=blocks,
            engine_name=self.name,
            engine_version=self.version,
            metadata={"mime_type": page.mime_type, "image_width": width, "image_height": height},
        )


def _package_version(package: str) -> str:
    try:
        from importlib.metadata import version

        return version(package)
    except Exception:
        return "unknown"
