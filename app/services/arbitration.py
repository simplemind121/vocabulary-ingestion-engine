"""Arbitrate OCR lines the independent readers could not agree on.

A vision model is shown the printed line and asked what it says. Its answer is
never taken on trust: it is accepted only when it matches, character for
character, what one of the OCR readers already read. The model therefore acts
as one more independent reader, and a line is settled when the model and an
OCR engine agree. Anything else stays parked with the model's answer recorded
for a human to see.

A model's decision is stored as machine arbitration. It is never recorded as a
human review.
"""

from __future__ import annotations

import base64
import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import fitz
from sqlalchemy.orm import Session

from app.adapters.paddleocr import restore_spaces
from app.models import (
    Artifact,
    Page,
    ProcessingStep,
    ReviewTask,
    SourceBlock,
    SourceEntry,
    SourceEntryBlock,
)
from app.services.ocr_consensus import _canonical, _mask_ipa
from app.services.ocr_quality import DEFERRED, READERS_DISAGREE

ARBITRATED = "ARBITRATED"
_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
_LINE_HEIGHT = 46.0
_SHEET_WIDTH = 1500.0
_LABEL_WIDTH = 56.0
_PROMPT = (
    "The image shows numbered lines cropped from a scanned vocabulary book that mixes "
    "English, Simplified Chinese and phonetic transcription. For each numbered line, "
    "transcribe exactly what is printed: do not correct spelling, do not translate, do not "
    "normalise punctuation, and keep arrows and brackets as printed. OCR candidates are "
    "listed per line; when one of them is exactly right, return it unchanged. If a line is "
    'unreadable, return null for it. Reply with JSON only: {"lines": [{"n": 1, "text": "..."}]}.'
)


class LineArbiter(Protocol):
    name: str

    def read_lines(self, image_png: bytes, items: list[dict]) -> dict[int, str | None]: ...


@dataclass(slots=True)
class OpenAIChatArbiter:
    """A vision model behind the OpenAI Chat Completions API (or a compatible endpoint)."""

    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 300.0
    max_attempts: int = 5
    backoff: float = 1.0
    # Token counts reported by the API, summed over every request made.
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    # Why a batch came back without an answer, one note per such request.
    unanswered: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"openai:{self.model}"

    def read_lines(self, image_png: bytes, items: list[dict]) -> dict[int, str | None]:
        candidates = "\n".join(
            f"{item['n']}: " + " | ".join(json.dumps(text, ensure_ascii=False) for text in item["candidates"])
            for item in items
        )
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"{_PROMPT}\n\nOCR candidates:\n{candidates}"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,"
                                + base64.b64encode(image_png).decode("ascii"),
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
        }
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        body = self._send(request)
        for name in self.usage:
            self.usage[name] += int((body.get("usage") or {}).get(name) or 0)
        message = (body.get("choices") or [{}])[0].get("message") or {}
        raw = message.get("content")
        if not raw:
            # The model declined or returned nothing. That is no answer for
            # this batch, not a reason to abort the whole run.
            self.unanswered.append(str(message.get("refusal") or "empty response")[:200])
            return {}
        try:
            content = json.loads(raw)
        except json.JSONDecodeError:
            self.unanswered.append("reply was not valid JSON")
            return {}
        answers: dict[int, str | None] = {}
        for line in content.get("lines") or []:
            try:
                number = int(line["n"])
            except (KeyError, TypeError, ValueError):
                continue
            text = line.get("text")
            answers[number] = text if isinstance(text, str) and text.strip() else None
        return answers


    def _send(self, request: urllib.request.Request) -> dict:
        """POST with retries: a dropped connection or a busy server is not a verdict."""
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            if attempt:
                time.sleep(min(2.0**attempt, 30.0) * self.backoff)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in _RETRYABLE_STATUS:
                    raise  # a rejected key or a malformed request will not fix itself
                last = exc
            except (urllib.error.URLError, ssl.SSLError, TimeoutError, ConnectionError) as exc:
                last = exc
        raise RuntimeError(
            f"arbiter unreachable after {self.max_attempts} attempts: {last}"
        ) from last


def build_line_sheet(crops: list[tuple[int, Path, dict]]) -> bytes:
    """Stack numbered line crops into one image: (number, page image, bbox)."""
    document = fitz.open()
    sheet = document.new_page(width=_SHEET_WIDTH, height=_LINE_HEIGHT * len(crops) + 8)
    for index, (number, image_path, bbox) in enumerate(crops):
        source = fitz.open(str(image_path))
        try:
            page = source[0]
            width, height = page.rect.width, page.rect.height
            clip = fitz.Rect(
                max(float(bbox["x1"]) * width - 6, 0),
                max(float(bbox["y1"]) * height - 4, 0),
                min(float(bbox["x2"]) * width + 6, width),
                min(float(bbox["y2"]) * height + 4, height),
            )
            pixmap = page.get_pixmap(clip=clip, matrix=fitz.Matrix(2, 2), alpha=False)
        finally:
            source.close()
        top = 4 + index * _LINE_HEIGHT
        available = fitz.Rect(_LABEL_WIDTH, top, _SHEET_WIDTH - 4, top + _LINE_HEIGHT - 6)
        scale = min(available.width / pixmap.width, available.height / pixmap.height)
        target = fitz.Rect(
            available.x0,
            available.y0,
            available.x0 + pixmap.width * scale,
            available.y0 + pixmap.height * scale,
        )
        sheet.insert_image(target, pixmap=pixmap)
        sheet.insert_text((6, top + _LINE_HEIGHT * 0.6), str(number), fontsize=16, color=(0.8, 0, 0))
    payload = sheet.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).tobytes("png")
    document.close()
    return payload


def _comparable(text: str) -> str:
    return _canonical(_mask_ipa(text))[0]


def accept_answer(answer: str | None, candidates: dict[str, str]) -> tuple[str, str] | None:
    """Return (reader, text) when the model's answer is what an OCR reader read."""
    if not answer:
        return None
    wanted = _comparable(answer)
    for reader, text in candidates.items():
        if text and _comparable(text) == wanted:
            # The stored text is the OCR reader's; only spacing comes from the model.
            return reader, restore_spaces(text, answer, exact_only=True)
    return None


def arbitrate_parked_lines(
    db: Session,
    run_id: str,
    arbiter: LineArbiter,
    *,
    batch_size: int = 20,
    limit: int | None = None,
) -> dict:
    """Ask the arbiter about every parked line that belongs to an entry."""
    linked = {
        row.source_block_id
        for row in db.query(SourceEntryBlock.source_block_id)
        .join(SourceEntry, SourceEntry.id == SourceEntryBlock.source_entry_id)
        .filter(SourceEntry.processing_run_id == run_id)
    }
    tasks = [
        task
        for task in db.query(ReviewTask)
        .filter(
            ReviewTask.processing_run_id == run_id,
            ReviewTask.reason_code == READERS_DISAGREE,
            ReviewTask.status == DEFERRED,
        )
        .order_by(ReviewTask.created_at, ReviewTask.id)
        if task.target_entity_id in linked
        and "machine_arbitration" not in (task.source_context or {})
    ]
    if limit is not None:
        tasks = tasks[:limit]

    accepted = unresolved = requests = skipped = 0
    for start in range(0, len(tasks), batch_size):
        batch = tasks[start : start + batch_size]
        crops, items, blocks = [], [], {}
        for number, task in enumerate(batch, start=1):
            block = db.get(SourceBlock, task.target_entity_id)
            page = db.get(Page, block.page_id)
            artifact = db.get(Artifact, page.render_artifact_id)
            consensus = (block.metadata_json or {}).get("consensus") or {}
            candidates = {
                "primary": consensus.get("primary_text") or block.raw_text or "",
                **(consensus.get("other_readings") or {}),
            }
            crops.append((number, Path(artifact.object_key), block.bbox))
            items.append({"n": number, "candidates": list(dict.fromkeys(candidates.values()))})
            blocks[number] = (task, block, candidates)
        answers = arbiter.read_lines(build_line_sheet(crops), items)
        requests += 1
        if not answers:
            # Nothing came back for the whole batch: leave its lines untouched
            # so a later run can ask again, rather than recording a non-answer.
            skipped += len(batch)
            continue
        for number, (task, block, candidates) in blocks.items():
            answer = answers.get(number)
            verdict = accept_answer(answer, candidates)
            record = {
                "arbiter": arbiter.name,
                "answer": answer,
                "decided_at": datetime.now(UTC).isoformat(),
                "status": "ACCEPTED" if verdict else "NOT_CONFIRMED",
            }
            if verdict:
                reader, text = verdict
                record.update({"agrees_with": reader, "text": text})
                block.metadata_json = {**(block.metadata_json or {}), "machine_arbitration": record}
                task.status = ARBITRATED
                accepted += 1
            else:
                unresolved += 1
            task.source_context = {**(task.source_context or {}), "machine_arbitration": record}
        db.commit()

    if accepted:
        # Entries were cut from the old text: make the next pass rebuild them.
        step = (
            db.query(ProcessingStep)
            .filter(ProcessingStep.processing_run_id == run_id, ProcessingStep.sequence_no == 20)
            .one_or_none()
        )
        if step is not None:
            step.metrics = {**(step.metrics or {}), "blocks_fingerprint": "stale"}
            db.commit()
    return {
        "run_id": run_id,
        "arbiter": arbiter.name,
        "lines": len(tasks),
        "requests": requests,
        "accepted": accepted,
        "not_confirmed": unresolved,
        "unanswered_lines": skipped,
        "unanswered_reasons": sorted(set(getattr(arbiter, "unanswered", []))),
        "usage": getattr(arbiter, "usage", None),
    }
