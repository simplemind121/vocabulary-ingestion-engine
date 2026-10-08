from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.adapters.paddleocr import _group_rows, restore_spaces
from app.idr import TextBlock
from app.services.ocr_consensus import DISPUTED, SINGLE_READER, build_consensus

# A line no second reader could confirm must reach a human: this keeps it
# below any sensible auto-accept threshold.
_UNCONFIRMED_CONFIDENCE = 0.5


class HttpRowReader:
    """A reader reached over HTTP: PNG in, text rows with normalized boxes out.

    Used for engines that cannot run inside the container, such as the macOS
    Vision framework served by a small helper on the host.
    """

    def __init__(self, name: str, url: str, *, timeout: float = 120.0) -> None:
        self.name = name
        self._url = url
        self._timeout = timeout

    def read_rows(self, page: OcrPageInput) -> list[dict]:
        request = urllib.request.Request(
            self._url, data=page.image_bytes, headers={"Content-Type": "image/png"}
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.load(response)["rows"]


class FileRowReader:
    """Readings produced elsewhere and shipped as files.

    Layout: ``<root>/<document sha256>/<reader name>/p0001.json``, each file a
    list of rows with normalized boxes. A page without a file is a page this
    reader did not read: it abstains there.
    """

    def __init__(self, name: str, root: str | Path) -> None:
        self.name = name
        self._root = Path(root)

    def read_rows(self, page: OcrPageInput) -> list[dict]:
        if not page.document_sha256:
            return []
        path = self._root / page.document_sha256 / self.name / f"p{page.page_number:04d}.json"
        if not path.is_file():
            return []
        return json.loads(path.read_text(encoding="utf-8"))


class AdapterRowReader:
    """Any OCR adapter used as a secondary reader."""

    def __init__(self, adapter: Any) -> None:
        self.name = adapter.name
        self._adapter = adapter

    def read_rows(self, page: OcrPageInput) -> list[dict]:
        return [
            {"text": block.text, **{k: v for k, v in block.bbox.as_dict().items() if k != "unit"}}
            for block in self._adapter.extract_page(page).blocks
        ]


class ConsensusOcrAdapter:
    """Several independent readers per page, voted line by line.

    The primary adapter defines the lines. Each secondary reader's text for
    the same band of the page is voted against it character by character.
    Lines the readers cannot agree on keep every reading and are capped to a
    low confidence so the existing OCR review picks them up.
    """

    name = "ocr-consensus"

    def __init__(self, primary: Any, secondaries: list[Any]) -> None:
        self._primary = primary
        self._secondaries = secondaries
        self.version = "+".join([primary.name, *[reader.name for reader in secondaries]])

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        # The readers are independent engines, so they read the page at once.
        with ThreadPoolExecutor(max_workers=1 + len(self._secondaries)) as pool:
            primary = pool.submit(self._primary.extract_page, page)
            secondary = [pool.submit(reader.read_rows, page) for reader in self._secondaries]
            result = primary.result()
            rows_by_reader = [future.result() for future in secondary]
        readings = []
        for reader, reader_rows in zip(self._secondaries, rows_by_reader, strict=True):
            parts = [
                dict(row)
                for row in reader_rows
                if not (row["x2"] <= 0.03 or row["x1"] >= 0.97)
            ]
            readings.append(
                (
                    reader.name,
                    [
                        {
                            "text": " ".join(part["text"] for part in row),
                            "y1": min(part["y1"] for part in row),
                            "y2": max(part["y2"] for part in row),
                        }
                        for row in _group_rows(parts)
                    ],
                )
            )

        blocks: list[TextBlock] = []
        for block in result.blocks:
            others = {
                name: text
                for name, rows in readings
                if (text := _aligned_text(rows, block.bbox.y1, block.bbox.y2))
            }
            consensus = build_consensus(block.text, list(others.values()))
            text = consensus.text
            for other in others.values():
                # Spacing only: adopted where the letters are identical.
                text = restore_spaces(text, other, exact_only=True)
            confirmed = consensus.status not in {DISPUTED, SINGLE_READER}
            blocks.append(
                TextBlock(
                    text=text,
                    bbox=block.bbox,
                    reading_order=block.reading_order,
                    confidence=(
                        block.confidence
                        if confirmed
                        else min(block.confidence or 0.0, _UNCONFIRMED_CONFIDENCE)
                    ),
                    block_type=block.block_type,
                    metadata={
                        **block.metadata,
                        "consensus": {
                            "status": consensus.status,
                            "readers": consensus.readers,
                            "corrections": consensus.corrections,
                            "disputes": consensus.disputes,
                            "primary_text": block.text,
                            "primary_confidence": block.confidence,
                            "other_readings": others,
                        },
                    },
                )
            )
        return OcrPageResult(
            page_number=result.page_number,
            blocks=blocks,
            engine_name=self.name,
            engine_version=self.version,
            metadata={**result.metadata, "readers": self.version},
        )


def _aligned_text(rows: list[dict], top: float, bottom: float) -> str | None:
    matched = [
        row
        for row in rows
        if min(row["y2"], bottom) - max(row["y1"], top)
        > 0.5 * min(row["y2"] - row["y1"], bottom - top)
    ]
    return " ".join(row["text"] for row in matched) if matched else None
