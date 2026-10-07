from __future__ import annotations

import io
import re
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.idr import BoundingBox, TextBlock

# A run of unspaced Latin letters this long is a sentence the Chinese model
# glued together, not a word.
_GLUED_LATIN = re.compile(r"[A-Za-z]{15,}")
_ASCII_RUN = re.compile(r"[\x21-\x7e][\x20-\x7e]*[\x21-\x7e]")
_MIN_RUN_LETTERS = 8
_MARGIN = 0.03


class PaddleOcrAdapter:
    """Optional PaddleOCR adapter isolated behind the stable OCR contract.

    PaddleOCR is imported lazily so the base API remains lightweight and can be
    deployed without OCR dependencies. Production OCR images can install the
    dedicated OCR extra and select this adapter through configuration.

    With ``lang="ch"`` the mixed Chinese/English model reads both scripts but
    drops the spaces between English words. Lines where that happened are read
    a second time by the English recognition model, and its spacing is adopted
    only where its letters agree exactly with the first reading.
    """

    name = "paddleocr"

    def __init__(
        self,
        engine: Any | None = None,
        *,
        lang: str = "ch",
        english_engine: Any | None = None,
    ) -> None:
        if engine is None:
            engine = _build_engine(lang)
            if english_engine is None and lang != "en":
                english_engine = _build_engine("en")
        self._engine = engine
        self._english = english_engine
        self.lang = lang
        self.version = _package_version("paddleocr")

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        try:
            import numpy as np
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("PaddleOCR adapter requires Pillow and numpy") from exc

        image = Image.open(io.BytesIO(page.image_bytes)).convert("RGB")
        width, height = image.size
        pixels = np.asarray(image)
        raw = self._engine.ocr(pixels, cls=False)

        # PaddleOCR classic API returns one list of [polygon, (text, score)]
        # records per input image. Keep normalization here so no Paddle-specific
        # shape escapes into the canonical IDR.
        records = raw[0] if raw and isinstance(raw, list) else []
        parts: list[dict] = []
        for record in records or []:
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
            part = {
                "text": text,
                "confidence": confidence,
                "x1": max(min(xs), 0.0),
                "y1": max(min(ys), 0.0),
                "x2": min(max(xs), float(width)),
                "y2": min(max(ys), float(height)),
                "refined": False,
            }
            if part["x2"] <= _MARGIN * width or part["x1"] >= (1 - _MARGIN) * width:
                # Scanner shadows and binding marks at the very edge of the page.
                continue
            if self._english is not None and _GLUED_LATIN.search(text):
                refined = restore_spaces(text, self._read_english(pixels, part))
                part["refined"] = refined != text
                part["text"] = refined
            parts.append(part)

        blocks: list[TextBlock] = []
        for order, row in enumerate(_group_rows(parts)):
            blocks.append(
                TextBlock(
                    text=" ".join(part["text"] for part in row),
                    bbox=BoundingBox(
                        x1=min(part["x1"] for part in row) / width,
                        y1=min(part["y1"] for part in row) / height,
                        x2=max(part["x2"] for part in row) / width,
                        y2=max(part["y2"] for part in row) / height,
                    ),
                    reading_order=order,
                    confidence=min(part["confidence"] for part in row),
                    block_type="TEXT",
                    metadata={
                        "ocr_engine": self.name,
                        "ocr_lang": self.lang,
                        "english_spacing_restored": any(part["refined"] for part in row),
                    },
                )
            )

        return OcrPageResult(
            page_number=page.page_number,
            blocks=blocks,
            engine_name=self.name,
            engine_version=self.version,
            metadata={"mime_type": page.mime_type, "image_width": width, "image_height": height},
        )

    def _read_english(self, pixels: Any, part: dict) -> str:
        pad = 2
        crop = pixels[
            max(int(part["y1"]) - pad, 0) : int(part["y2"]) + pad,
            max(int(part["x1"]) - pad, 0) : int(part["x2"]) + pad,
        ]
        if crop.size == 0:
            return ""
        result = self._english.ocr(crop, det=False, cls=False)
        try:
            return str(result[0][0][0])
        except (IndexError, TypeError):
            return ""


def restore_spaces(text: str, english: str) -> str:
    """Adopt word spacing from ``english`` wherever its characters match ``text``.

    Only whitespace is ever taken from the second reading: a Latin run is
    replaced solely by a stretch of ``english`` that is character-for-character
    identical once spaces are removed. Anything the two readings disagree on is
    left exactly as first read.
    """
    if not english:
        return text
    squashed: list[str] = []
    origin: list[int] = []
    for index, character in enumerate(english):
        if not character.isspace():
            squashed.append(character)
            origin.append(index)
    haystack = "".join(squashed)

    def replace(match: re.Match[str]) -> str:
        run = match.group(0)
        if sum(character.isalpha() for character in run) < _MIN_RUN_LETTERS:
            return run
        key = "".join(run.split())
        start = haystack.find(key)
        if start < 0:
            return run
        candidate = english[origin[start] : origin[start + len(key) - 1] + 1]
        return candidate if " " in candidate and len(candidate) >= len(run) else run

    return _ASCII_RUN.sub(replace, text)


def _group_rows(parts: list[dict]) -> list[list[dict]]:
    """Reading order: rows top to bottom, fragments of one row left to right."""
    rows: list[list[dict]] = []
    for part in sorted(parts, key=lambda item: ((item["y1"] + item["y2"]) / 2, item["x1"])):
        current = rows[-1] if rows else None
        if current is not None:
            top = max(min(item["y1"] for item in current), part["y1"])
            bottom = min(max(item["y2"] for item in current), part["y2"])
            shortest = min(
                part["y2"] - part["y1"], min(item["y2"] - item["y1"] for item in current)
            )
            if shortest > 0 and (bottom - top) / shortest >= 0.6:
                current.append(part)
                continue
        rows.append([part])
    return [sorted(row, key=lambda item: item["x1"]) for row in rows]


def _build_engine(lang: str) -> Any:
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise RuntimeError(
            "PaddleOCR is not installed; install the OCR runtime before selecting paddleocr"
        ) from exc
    return PaddleOCR(
        use_angle_cls=False,
        lang=lang,
        show_log=False,
        rec_batch_num=2,
        cpu_threads=2,
        enable_mkldnn=False,
    )


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"
