from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.idr import TextBlock


@dataclass(slots=True)
class OcrPageInput:
    page_number: int
    image_bytes: bytes
    mime_type: str = "image/png"


@dataclass(slots=True)
class OcrPageResult:
    page_number: int
    blocks: list[TextBlock]
    engine_name: str
    engine_version: str
    metadata: dict


class OcrEngineAdapter(Protocol):
    name: str
    version: str

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        ...
