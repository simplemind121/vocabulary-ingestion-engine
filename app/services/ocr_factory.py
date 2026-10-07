from __future__ import annotations

from app.adapters.ocr_base import OcrEngineAdapter
from app.adapters.paddleocr import PaddleOcrAdapter
from app.adapters.tesseract import TesseractOcrAdapter
from app.settings import Settings


def build_ocr_adapter(settings: Settings) -> OcrEngineAdapter | None:
    engine = settings.ocr_engine.strip().lower()
    if engine in {"", "none", "disabled"}:
        return None
    if engine == "paddleocr":
        # The mixed Chinese/English model unless the book is declared English-only.
        languages = settings.ocr_languages.lower()
        return PaddleOcrAdapter(lang="ch" if "chi" in languages or "ch" == languages else "en")
    if engine == "tesseract":
        return TesseractOcrAdapter(languages=settings.ocr_languages)
    raise ValueError(f"unsupported OCR engine: {settings.ocr_engine}")
