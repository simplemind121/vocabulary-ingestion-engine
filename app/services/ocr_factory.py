from __future__ import annotations

from app.adapters.consensus import (
    AdapterRowReader,
    ConsensusOcrAdapter,
    FileRowReader,
    HttpRowReader,
)
from app.adapters.ocr_base import OcrEngineAdapter
from app.adapters.paddleocr import PaddleOcrAdapter
from app.adapters.rapidocr import RapidOcrAdapter
from app.adapters.tesseract import TesseractOcrAdapter
from app.settings import Settings


def build_ocr_adapter(settings: Settings) -> OcrEngineAdapter | None:
    primary = _build_primary(settings)
    if primary is None:
        return None
    names = [name.strip().lower() for name in settings.ocr_secondary_readers.split(",")]
    readers = [_build_reader(name, settings) for name in names if name]
    if not readers:
        return primary
    return ConsensusOcrAdapter(primary, readers)


def _build_reader(name: str, settings: Settings):
    if name == "vision":
        if not settings.vision_ocr_url:
            raise ValueError("the vision reader requires VIE_VISION_OCR_URL")
        return HttpRowReader("macos-vision", settings.vision_ocr_url)
    if name == "vision-import":
        if not settings.ocr_readings_root:
            raise ValueError("the vision-import reader requires VIE_OCR_READINGS_ROOT")
        return FileRowReader("macos-vision", settings.ocr_readings_root)
    if name == "rapidocr-v5":
        return AdapterRowReader(RapidOcrAdapter(lang="ch", ocr_version="PP-OCRv5", refine=False))
    raise ValueError(f"unsupported secondary OCR reader: {name}")


def _build_primary(settings: Settings) -> OcrEngineAdapter | None:
    engine = settings.ocr_engine.strip().lower()
    if engine in {"", "none", "disabled"}:
        return None
    if engine == "rapidocr":
        languages = settings.ocr_languages.lower()
        return RapidOcrAdapter(lang="ch" if "ch" in languages else "en")
    if engine == "paddleocr":
        # The mixed Chinese/English model unless the book is declared English-only.
        languages = settings.ocr_languages.lower()
        return PaddleOcrAdapter(lang="ch" if "chi" in languages or "ch" == languages else "en")
    if engine == "tesseract":
        return TesseractOcrAdapter(languages=settings.ocr_languages)
    raise ValueError(f"unsupported OCR engine: {settings.ocr_engine}")
