from __future__ import annotations

from app.adapters.ocr_base import OcrEngineAdapter
from app.adapters.paddleocr import PaddleOcrAdapter
from app.settings import Settings


def build_ocr_adapter(settings: Settings) -> OcrEngineAdapter | None:
    engine = settings.ocr_engine.strip().lower()
    if engine in {"", "none", "disabled"}:
        return None
    if engine == "paddleocr":
        return PaddleOcrAdapter()
    raise ValueError(f"unsupported OCR engine: {settings.ocr_engine}")
