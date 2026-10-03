from __future__ import annotations

import csv
import io
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.idr import BoundingBox, TextBlock


class TesseractOcrAdapter:
    """Dependency-light production OCR adapter backed by the Tesseract CLI."""

    name = "tesseract"

    def __init__(
        self,
        *,
        executable: str = "tesseract",
        languages: str = "eng+chi_sim",
        runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
    ) -> None:
        if not languages.strip():
            raise ValueError("Tesseract OCR languages must not be empty")
        if runner is None and shutil.which(executable) is None:
            raise RuntimeError(
                "Tesseract is not installed; install tesseract-ocr and the configured languages"
            )
        self.executable = executable
        self.languages = languages.strip()
        self._runner = runner or subprocess.run
        version = self._run([self.executable, "--version"])
        first_line = (version.stdout or b"").decode("utf-8", errors="replace").splitlines()
        self.version = first_line[0].removeprefix("tesseract ").strip() if first_line else "unknown"

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        completed = self._run(
            [
                self.executable,
                "stdin",
                "stdout",
                "--dpi",
                "300",
                "-l",
                self.languages,
                "tsv",
            ],
            input=page.image_bytes,
        )
        rows = list(
            csv.DictReader(
                io.StringIO(completed.stdout.decode("utf-8", errors="replace")),
                delimiter="\t",
            )
        )
        width, height = _page_dimensions(rows)
        if width <= 0 or height <= 0:
            raise RuntimeError("Tesseract returned TSV without valid page dimensions")

        lines: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if _integer(row.get("level")) != 5:
                continue
            text = str(row.get("text") or "").strip()
            confidence = _number(row.get("conf"))
            if not text or confidence < 0:
                continue
            key = (
                _integer(row.get("block_num")),
                _integer(row.get("par_num")),
                _integer(row.get("line_num")),
            )
            lines[key].append({**row, "text": text, "confidence": confidence})

        blocks = []
        for order, key in enumerate(sorted(lines)):
            words = sorted(
                lines[key],
                key=lambda row: (_integer(row.get("word_num")), _integer(row.get("left"))),
            )
            left = min(_integer(word.get("left")) for word in words)
            top = min(_integer(word.get("top")) for word in words)
            right = max(
                _integer(word.get("left")) + _integer(word.get("width")) for word in words
            )
            bottom = max(
                _integer(word.get("top")) + _integer(word.get("height")) for word in words
            )
            blocks.append(
                TextBlock(
                    text=" ".join(str(word["text"]) for word in words),
                    bbox=BoundingBox(
                        x1=_clamp(left / width),
                        y1=_clamp(top / height),
                        x2=_clamp(right / width),
                        y2=_clamp(bottom / height),
                    ),
                    reading_order=order,
                    confidence=sum(float(word["confidence"]) for word in words)
                    / (100 * len(words)),
                    metadata={
                        "ocr_engine": self.name,
                        "ocr_languages": self.languages,
                        "word_count": len(words),
                    },
                )
            )

        return OcrPageResult(
            page_number=page.page_number,
            blocks=blocks,
            engine_name=self.name,
            engine_version=self.version,
            metadata={
                "mime_type": page.mime_type,
                "image_width": width,
                "image_height": height,
                "languages": self.languages,
            },
        )

    def _run(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        completed = self._runner(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            **kwargs,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Tesseract OCR failed: {detail[:500]}")
        return completed


def _page_dimensions(rows: list[dict[str, str]]) -> tuple[int, int]:
    page = next((row for row in rows if _integer(row.get("level")) == 1), None)
    if page is not None:
        return _integer(page.get("width")), _integer(page.get("height"))
    return (
        max(
            (_integer(row.get("left")) + _integer(row.get("width")) for row in rows),
            default=0,
        ),
        max(
            (_integer(row.get("top")) + _integer(row.get("height")) for row in rows),
            default=0,
        ),
    )


def _integer(value: Any) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


def _number(value: Any) -> float:
    try:
        return float(str(value or "-1"))
    except ValueError:
        return -1.0


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)
