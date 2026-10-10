from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.idr import TextBlock


@dataclass(slots=True)
class OcrPageInput:
    page_number: int
    image_bytes: bytes
    mime_type: str = "image/png"
    # Identity of the source document, for readers keyed by it (imported readings).
    document_sha256: str | None = None


@dataclass(slots=True)
class OcrPageResult:
    page_number: int
    blocks: list[TextBlock]
    engine_name: str
    engine_version: str
    metadata: dict = field(default_factory=dict)


class OcrEngineAdapter(Protocol):
    name: str
    version: str

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        ...
