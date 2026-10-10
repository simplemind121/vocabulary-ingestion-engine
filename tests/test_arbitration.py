import io
import json

from app.db import SessionLocal
from app.models import ReviewTask, SourceBlock, VocabularyEntry, VocabularyField
from app.services.arbitration import (
    OpenAIChatArbiter,
    accept_answer,
    arbitrate_parked_lines,
)
from app.services.pipeline import run_pipeline
from app.services.review import resolve_review_task
from tests.test_scanned_book import ScannedBookOcr, _upload

LINE = "【例】The boy wondered how it was composed.这个小男孩想知道。"
VISION = "【例】The boy wondered how it was conposed.这个小男孩想知道。"


class TwoReadingsOcr(ScannedBookOcr):
    """One example line read two ways; nothing else is in doubt."""

    def extract_page(self, page):
        result = super().extract_page(page)
        for block in result.blocks:
            disputed = block.text == LINE
            block.metadata = {
                "consensus": {
                    "status": "DISPUTED" if disputed else "UNANIMOUS",
                    "readers": 2,
                    "primary_text": block.text,
                    "disputes": [{"base": "m", "others": ["n"]}] if disputed else [],
                    "other_readings": {"macos-vision": VISION} if disputed else {},
                }
            }
            if disputed:
                block.confidence = 0.5
        return result


class FakeArbiter:
    name = "fake-arbiter"

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def read_lines(self, image_png, items):
        assert image_png.startswith(b"\x89PNG")
        self.calls.append(items)
        return {item["n"]: self.answer for item in items}


def _parked_run(client):
    run_id = _upload(client)
    db = SessionLocal()
    run_pipeline(db, run_id, ocr_adapter=TwoReadingsOcr())
    for task in db.query(ReviewTask).filter(
        ReviewTask.processing_run_id == run_id, ReviewTask.status == "OPEN"
    ):
        resolution = {"decision": "ACCEPT"}
        if task.target_entity_type == "Page":
            resolution["classification"] = "NOT_AN_ENTRY_PAGE"
        else:
            resolution["corrected_text"] = "incur[x]vt.招致"
        resolve_review_task(db, task.id, resolution=resolution, reviewer_id="reviewer-1")
    assert run_pipeline(db, run_id, ocr_adapter=TwoReadingsOcr())["blocked_gate"] == "G6"
    return db, run_id


def test_answer_is_accepted_only_when_an_ocr_reader_read_the_same():
    candidates = {"primary": "回味无穷[x]n.", "macos-vision": "回昧无穷 [y] n."}
    assert accept_answer("回昧无穷 [zzz] n.", candidates) == ("macos-vision", "回昧无穷 [y] n.")
    assert accept_answer("回未无穷[x]n.", candidates) is None  # a third reading settles nothing
    assert accept_answer(None, candidates) is None
    assert accept_answer("", candidates) is None


def test_model_agreeing_with_a_reader_settles_the_line_and_entries_are_rebuilt(client):
    db, run_id = _parked_run(client)
    try:
        arbiter = FakeArbiter(VISION)
        result = arbitrate_parked_lines(db, run_id, arbiter)
        assert (result["lines"], result["requests"], result["accepted"]) == (1, 1, 1)
        assert arbiter.calls[0][0]["candidates"] == [LINE, VISION]

        task = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.processing_run_id == run_id,
                ReviewTask.reason_code == "OCR_READERS_DISAGREE",
            )
            .one()
        )
        assert task.status == "ARBITRATED"
        block = db.get(SourceBlock, task.target_entity_id)
        assert block.raw_text == LINE  # the OCR observation itself is never rewritten
        assert "human_ocr_review" not in block.metadata_json  # and no human is credited
        assert block.metadata_json["machine_arbitration"]["agrees_with"] == "macos-vision"

        final = run_pipeline(db, run_id, ocr_adapter=TwoReadingsOcr())
        assert final["status"] == "COMPLETED"
        compose = (
            db.query(VocabularyEntry)
            .filter(VocabularyEntry.processing_run_id == run_id, VocabularyEntry.lemma == "compose")
            .one()
        )
        assert compose.verification_status == "AUTO_VERIFIED"
        example = (
            db.query(VocabularyField)
            .filter(
                VocabularyField.vocabulary_entry_id == compose.id,
                VocabularyField.field_type == "EXAMPLE",
            )
            .one()
        )
        assert "conposed" in example.text
        # Already arbitrated: a second request costs nothing.
        assert arbitrate_parked_lines(db, run_id, FakeArbiter(VISION))["lines"] == 0
    finally:
        db.close()


def test_an_answer_no_reader_shares_leaves_the_line_parked(client):
    db, run_id = _parked_run(client)
    try:
        result = arbitrate_parked_lines(db, run_id, FakeArbiter("something else entirely"))
        assert (result["accepted"], result["not_confirmed"]) == (0, 1)
        task = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.processing_run_id == run_id,
                ReviewTask.reason_code == "OCR_READERS_DISAGREE",
            )
            .one()
        )
        assert task.status == "DEFERRED"
        assert task.source_context["machine_arbitration"]["answer"] == "something else entirely"
        assert run_pipeline(db, run_id, ocr_adapter=TwoReadingsOcr())["blocked_gate"] == "G6"
    finally:
        db.close()


def test_openai_arbiter_sends_one_image_and_parses_numbered_answers(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["body"] = json.loads(request.data)
        reply = {"lines": [{"n": 1, "text": "first"}, {"n": "2", "text": ""}, {"text": "x"}]}
        return io.BytesIO(
            json.dumps({"choices": [{"message": {"content": json.dumps(reply)}}]}).encode()
        )

    monkeypatch.setattr("app.services.arbitration.urllib.request.urlopen", fake_urlopen)
    arbiter = OpenAIChatArbiter(api_key="test-key", model="some-model", base_url="http://x/v1/")
    answers = arbiter.read_lines(b"\x89PNG-bytes", [{"n": 1, "candidates": ["a", "b"]}])

    assert answers == {1: "first", 2: None}
    assert seen["url"] == "http://x/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "some-model"
    parts = seen["body"]["messages"][0]["content"]
    assert [part["type"] for part in parts] == ["text", "image_url"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert '1: "a" | "b"' in parts[0]["text"]
    assert arbiter.name == "openai:some-model"


def test_openai_arbiter_retries_dropped_connections_but_not_rejections(monkeypatch):
    import ssl
    import urllib.error

    import pytest

    reply = json.dumps(
        {
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            "choices": [{"message": {"content": json.dumps({"lines": [{"n": 1, "text": "ok"}]})}}],
        }
    ).encode()
    failures = [
        ssl.SSLError("EOF occurred in violation of protocol"),
        urllib.error.URLError("connection reset"),
        urllib.error.HTTPError("u", 503, "busy", None, None),
    ]
    calls = []

    def flaky(request, timeout):
        calls.append(1)
        if failures:
            raise failures.pop(0)
        return io.BytesIO(reply)

    monkeypatch.setattr("app.services.arbitration.urllib.request.urlopen", flaky)
    arbiter = OpenAIChatArbiter(api_key="k", model="m", backoff=0.0)
    assert arbiter.read_lines(b"png", [{"n": 1, "candidates": ["ok"]}]) == {1: "ok"}
    assert len(calls) == 4
    assert arbiter.usage == {"prompt_tokens": 11, "completion_tokens": 7}

    def rejected(request, timeout):
        calls.append(1)
        raise urllib.error.HTTPError("u", 401, "unauthorized", None, None)

    calls.clear()
    monkeypatch.setattr("app.services.arbitration.urllib.request.urlopen", rejected)
    with pytest.raises(urllib.error.HTTPError):
        arbiter.read_lines(b"png", [{"n": 1, "candidates": ["ok"]}])
    assert len(calls) == 1  # an invalid key is not retried

    def always_down(request, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr("app.services.arbitration.urllib.request.urlopen", always_down)
    with pytest.raises(RuntimeError, match="unreachable after 5 attempts"):
        arbiter.read_lines(b"png", [{"n": 1, "candidates": ["ok"]}])
