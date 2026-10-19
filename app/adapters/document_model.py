"""Document models: readers that see a whole page and return its regions.

A document model (GLM-OCR, PaddleOCR-VL, MinerU and the like) reads a page as
regions: text, table, image and formula areas, each with a page-relative box
and its content (text as Markdown, tables as HTML). It complements the line
readers, which find lines first and then read them.

Every reading records the model, the model's version as the service reports it,
and a hash of the raw response, so a silent change of model can be noticed. A
model reached over a paid API sits behind ``CachedDocumentReader``: each page is
read once, kept on disk, and paid for once; a run's budget stops further calls.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from app.adapters.ocr_base import OcrPageInput


@dataclass(slots=True)
class Region:
    label: str  # "text", "table", "image", "formula"
    box: tuple[float, float, float, float]  # page fractions: x1, y1, x2, y2
    content: str
    order: int


@dataclass(slots=True)
class DocumentReading:
    page_number: int
    regions: list[Region]
    markdown: str
    model: str
    model_version: str | None
    response_sha256: str
    usage: dict = field(default_factory=dict)
    cached: bool = False

    def to_json(self) -> dict:
        data = asdict(self)
        data["regions"] = [{**asdict(r), "box": list(r.box)} for r in self.regions]
        return data

    @classmethod
    def from_json(cls, data: dict) -> DocumentReading:
        regions = [Region(r["label"], tuple(r["box"]), r["content"], r["order"]) for r in data["regions"]]
        return cls(**{**data, "regions": regions})


class DocumentModelReader(Protocol):
    name: str

    def read_document_page(self, page: OcrPageInput) -> DocumentReading: ...


class GlmOcrReader:
    """GLM-OCR through the Z.ai layout-parsing API: one page image per request."""

    name = "glm-ocr"

    def __init__(
        self,
        api_key: str,
        *,
        url: str = "https://api.z.ai/api/paas/v4/layout_parsing",
        model: str = "glm-ocr",
        timeout: float = 180.0,
        retries: int = 3,
        opener=urllib.request.urlopen,
    ) -> None:
        self._api_key = api_key
        self._url = url
        self._model = model
        self._timeout = timeout
        self._retries = retries
        self._open = opener

    def read_document_page(self, page: OcrPageInput) -> DocumentReading:
        image = base64.b64encode(page.image_bytes).decode("ascii")
        body = json.dumps({"model": self._model, "file": f"data:{page.mime_type};base64,{image}"}).encode()
        raw = self._post(body)
        return parse_glm_response(raw, page.page_number)

    def _post(self, body: bytes) -> bytes:
        request = urllib.request.Request(
            self._url,
            data=body,
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
        )
        for attempt in range(self._retries + 1):
            try:
                with self._open(request, timeout=self._timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                # Only rate limits and server errors are worth another try.
                if error.code not in (429, 500, 502, 503, 504) or attempt == self._retries:
                    raise RuntimeError(f"glm-ocr request failed with HTTP {error.code}") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt == self._retries:
                    raise
            time.sleep(2**attempt)
        raise AssertionError("unreachable")


def parse_glm_response(raw: bytes, page_number: int) -> DocumentReading:
    """The layout-parsing response: ``md_results`` and ``layout_details`` (per page, a list of regions)."""
    data = json.loads(raw)
    details = data.get("layout_details") or []
    if details and isinstance(details[0], dict):
        details = [details]  # a single page, not nested
    pages = (data.get("data_info") or {}).get("pages") or [{}]
    regions = []
    for order, item in enumerate(details[0] if details else []):
        box = [float(v) for v in (item.get("bbox_2d") or [0, 0, 0, 0])]
        # The service documents fractions but answers in pixels of the image sent:
        # boxes are made page-relative with the page's own size.
        width = float(item.get("width") or pages[0].get("width") or 0)
        height = float(item.get("height") or pages[0].get("height") or 0)
        if max(box) > 1.5 and width and height:
            box = [box[0] / width, box[1] / height, box[2] / width, box[3] / height]
        regions.append(
            Region(
                label=str(item.get("label") or "text"),
                box=tuple(round(min(max(v, 0.0), 1.0), 4) for v in box),
                content=str(item.get("content") or ""),
                order=int(item.get("index", order)),
            )
        )
    return DocumentReading(
        page_number=page_number,
        regions=sorted(regions, key=lambda r: r.order),
        markdown=str(data.get("md_results") or ""),
        model=str(data.get("model") or "glm-ocr"),
        model_version=data.get("model_version") or data.get("model"),
        response_sha256=hashlib.sha256(raw).hexdigest(),
        usage=dict(data.get("usage") or {}),
    )


class BudgetExhausted(RuntimeError):
    pass


class Budget:
    """A limit on tokens and requests for one run; shared by the threads reading pages."""

    def __init__(self, *, max_tokens: int | None = None, max_requests: int | None = None) -> None:
        self.max_tokens = max_tokens
        self.max_requests = max_requests
        self.tokens = 0
        self.requests = 0
        self._lock = threading.Lock()

    def reserve(self) -> None:
        with self._lock:
            if self.max_requests is not None and self.requests >= self.max_requests:
                raise BudgetExhausted("request limit reached")
            if self.max_tokens is not None and self.tokens >= self.max_tokens:
                raise BudgetExhausted("token limit reached")
            self.requests += 1

    def charge(self, usage: dict) -> None:
        with self._lock:
            self.tokens += int(usage.get("total_tokens") or 0)


class CachedDocumentReader:
    """Reads a page once, keeps the reading on disk, and stays within a budget.

    Layout: ``<root>/<document sha256>/<reader name>/p0001.json``. A page not
    cached is read only while the budget allows; past it the reader abstains
    (returns None) and the page is read by the other readers alone.
    """

    def __init__(self, reader: DocumentModelReader, root: str | Path, budget: Budget | None = None) -> None:
        self.reader = reader
        self.name = reader.name
        self._root = Path(root)
        self.budget = budget or Budget()
        self.abstained: list[int] = []

    def _path(self, page: OcrPageInput) -> Path | None:
        if not page.document_sha256 or page.page_number < 1:
            return None
        return self._root / page.document_sha256 / self.name / f"p{page.page_number:04d}.json"

    def read_document_page(self, page: OcrPageInput) -> DocumentReading | None:
        path = self._path(page)
        if path is not None and path.is_file():
            reading = DocumentReading.from_json(json.loads(path.read_text(encoding="utf-8")))
            reading.cached = True
            return reading
        try:
            self.budget.reserve()
        except BudgetExhausted:
            self.abstained.append(page.page_number)
            return None
        reading = self.reader.read_document_page(page)
        self.budget.charge(reading.usage)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(reading.to_json(), ensure_ascii=False), encoding="utf-8")
        return reading

    def versions(self, document_sha256: str) -> dict[str, int]:
        """How many cached pages each model version read: more than one means the model changed mid-book."""
        counts: dict[str, int] = {}
        for path in sorted((self._root / document_sha256 / self.name).glob("p*.json")):
            version = json.loads(path.read_text(encoding="utf-8")).get("model_version") or "unknown"
            counts[version] = counts.get(version, 0) + 1
        return counts


class RegionRowReader:
    """A document model offered to the line vote: each text region's lines, spread evenly over its box.

    A first approximation, until regions are aligned to lines word by word: it
    lets the model vote now, line bands taken from the region's height.
    """

    def __init__(self, reader: CachedDocumentReader) -> None:
        self.name = reader.name
        self._reader = reader

    def read_rows(self, page: OcrPageInput) -> list[dict]:
        reading = self._reader.read_document_page(page)
        if reading is None:
            return []
        rows = []
        for region in reading.regions:
            if region.label != "text":
                continue
            lines = [line.strip() for line in region.content.splitlines() if line.strip()]
            x1, y1, x2, y2 = region.box
            step = (y2 - y1) / max(len(lines), 1)
            for i, line in enumerate(lines):
                rows.append({"text": line, "x1": x1, "y1": y1 + i * step, "x2": x2, "y2": y1 + (i + 1) * step})
        return rows
