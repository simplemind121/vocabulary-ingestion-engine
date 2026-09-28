from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float
    unit: str = "normalized"

    def as_dict(self) -> dict:
        return {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "unit": self.unit,
        }


@dataclass(slots=True)
class TextBlock:
    text: str
    bbox: BoundingBox
    reading_order: int
    confidence: float | None = None
    block_type: str = "TEXT"
    metadata: dict = field(default_factory=dict)
