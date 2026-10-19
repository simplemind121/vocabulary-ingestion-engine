import io
import json
import urllib.error

import pytest

from app.adapters.document_model import (
    Budget,
    CachedDocumentReader,
    GlmOcrReader,
    RegionRowReader,
    parse_glm_response,
)
from app.adapters.ocr_base import OcrPageInput
from app.services.ocr_factory import _build_reader
from app.settings import Settings

RESPONSE = {
    "id": "task-1",
    "model": "glm-ocr",
    "md_results": "## Present continuous\n\nI am **doing** something now.\nShall I open the window?",
    "layout_details": [[
        {"index": 1, "label": "text", "bbox_2d": [0.05, 0.40, 0.95, 0.50], "content": "I am **doing** something now.\nShall I open the window?"},
        {"index": 0, "label": "text", "bbox_2d": [0.05, 0.08, 0.60, 0.12], "content": "Present continuous"},
        {"index": 2, "label": "image", "bbox_2d": [0.60, 0.60, 0.90, 0.80], "content": "https://example.invalid/crop.png"},
    ]],
    "data_info": {"num_pages": 1, "pages": [{"width": 800, "height": 1100}]},
    "usage": {"prompt_tokens": 900, "completion_tokens": 300, "total_tokens": 1200},
}


class FakeApi:
    def __init__(self, failures=()):
        self.calls = []
        self.failures = list(failures)

    def __call__(self, request, timeout):
        self.calls.append(json.loads(request.data))
        assert request.headers["Authorization"] == "Bearer test-key"
        if self.failures:
            raise urllib.error.HTTPError(request.full_url, self.failures.pop(0), "busy", {}, io.BytesIO(b""))
        return io.BytesIO(json.dumps(RESPONSE).encode())


def _page(number=1):
    return OcrPageInput(page_number=number, image_bytes=b"\x89PNG fake", document_sha256="abc123")


def test_boxes_in_pixels_are_made_page_relative():
    answer = {"md_results": "", "data_info": {"pages": [{"width": 1600, "height": 2200}]}, "layout_details": [[
        {"index": 0, "label": "text", "bbox_2d": [160, 220, 800, 440], "content": "x", "width": 1600, "height": 2200}]]}
    assert parse_glm_response(json.dumps(answer).encode(), 1).regions[0].box == (0.1, 0.1, 0.5, 0.2)


def test_the_response_becomes_regions_in_reading_order():
    reading = parse_glm_response(json.dumps(RESPONSE).encode(), 7)
    assert [r.content for r in reading.regions][:2] == ["Present continuous", "I am **doing** something now.\nShall I open the window?"]
    assert reading.regions[2].label == "image" and reading.regions[2].box == (0.6, 0.6, 0.9, 0.8)
    assert reading.page_number == 7 and reading.usage["total_tokens"] == 1200
    assert len(reading.response_sha256) == 64 and reading.model_version == "glm-ocr"


def test_a_busy_service_is_tried_again_and_the_image_is_sent_inline():
    api = FakeApi(failures=[429, 503])
    waits = []
    reading = GlmOcrReader("test-key", opener=api, sleep=waits.append).read_document_page(_page())
    assert waits == [5, 10]
    assert len(api.calls) == 3 and api.calls[0]["model"] == "glm-ocr"
    assert api.calls[0]["file"].startswith("data:image/png;base64,")
    assert reading.markdown.startswith("## Present continuous")
    with pytest.raises(RuntimeError, match="HTTP 401"):
        GlmOcrReader("test-key", opener=FakeApi(failures=[401]), sleep=waits.append).read_document_page(_page())


def test_pages_are_paid_for_once_and_the_budget_stops_the_rest(tmp_path):
    api = FakeApi()
    cached = CachedDocumentReader(GlmOcrReader("test-key", opener=api), tmp_path, Budget(max_requests=2))
    assert cached.read_document_page(_page(1)).cached is False
    again = cached.read_document_page(_page(1))
    assert again.cached is True and again.regions[0].content == "Present continuous"
    assert cached.read_document_page(_page(2)) is not None
    assert cached.read_document_page(_page(3)) is None and cached.abstained == [3]
    assert len(api.calls) == 2 and cached.budget.tokens == 2400
    assert cached.versions("abc123") == {"glm-ocr": 2}
    tokens = CachedDocumentReader(GlmOcrReader("test-key", opener=FakeApi()), tmp_path / "t", Budget(max_tokens=1000))
    assert tokens.read_document_page(_page(1)) is not None and tokens.read_document_page(_page(2)) is None


def test_text_regions_vote_as_rows_spread_over_their_box(tmp_path):
    rows = RegionRowReader(CachedDocumentReader(GlmOcrReader("test-key", opener=FakeApi()), tmp_path)).read_rows(_page())
    assert [r["text"] for r in rows] == ["Present continuous", "I am **doing** something now.", "Shall I open the window?"]
    assert rows[1]["y1"] == pytest.approx(0.40) and rows[2]["y1"] == pytest.approx(0.45) and rows[2]["y2"] == pytest.approx(0.50)


def test_the_reader_is_built_only_when_external_readers_are_allowed(tmp_path):
    with pytest.raises(ValueError, match="EXTERNAL_READERS_ALLOWED"):
        _build_reader("glm-ocr", Settings(glm_ocr_api_key="k"))
    with pytest.raises(ValueError, match="GLM_OCR_API_KEY"):
        _build_reader("glm-ocr", Settings(external_readers_allowed=True))
    reader = _build_reader("glm-ocr", Settings(external_readers_allowed=True, glm_ocr_api_key="k", storage_root=tmp_path,
                                               document_model_max_requests=5))
    assert reader.name == "glm-ocr" and reader._reader.budget.max_requests == 5
