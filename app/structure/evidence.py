"""What was read on a page: the run's voted lines, and the scan's own text layer.

A line is ``{"text", "box", "vote", "check", "readings"}``: the voted text, its
page-relative box ``[x1, y1, x2, y2]``, the consensus status, the arbitration
status of a disputed line, and every other reader's text for it.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy.orm import Session

WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9']*")


def words(text: str) -> list[str]:
    """Words for comparing a page with what was read: lower case, curly apostrophes made straight."""
    return [word.lower() for word in WORD.findall(text.replace("’", "'"))]


def readable_words(lines: list[dict], text_layer: Iterable[str] = ()) -> Counter:
    """Every word any reader read on the page, the hidden text layer included.

    The text layer holds lines the vote never saw because the primary reader
    did not detect them; it may supply words, it is not trusted for layout.
    """
    found: Counter = Counter()
    for line in lines:
        found.update(words(line["text"]))
        for other in (line.get("readings") or {}).values():
            found.update(words(other))
    for word in text_layer:
        found.update(words(word))
    return found


def text_layer_words(pdf_path: str | Path, page_number: int) -> list[str]:
    import fitz

    with fitz.open(pdf_path) as document:
        if not 0 < page_number <= document.page_count:
            return []
        return [word[4] for word in document[page_number - 1].get_text("words")]


def load_lines(path: str | Path) -> dict[int, list[dict]]:
    """Lines exported earlier (``lines.json``: page number to lines)."""
    return {int(page): lines for page, lines in json.loads(Path(path).read_text(encoding="utf-8")).items()}


def run_lines(db: Session, run_id: str) -> dict[int, list[dict]]:
    """Every line of a run, page by page, in reading order."""
    from app.models import Page, ProcessingRun, ReviewTask, SourceBlock
    from app.services.ocr_quality import READERS_DISAGREE
    from app.services.segmentation import _effective_block_text

    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    pages = {page.id: page.page_number for page in db.query(Page).filter(Page.document_version_id == run.document_version_id)}
    status = {}
    for task in db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.reason_code == READERS_DISAGREE):
        mark = (task.source_context or {}).get("machine_arbitration") or {}
        status[task.target_entity_id] = mark.get("status") or "UNASKED"
    out: dict[int, list[dict]] = {}
    blocks = db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id).order_by(SourceBlock.reading_order)
    for block in blocks:
        consensus = (block.metadata_json or {}).get("consensus") or {}
        out.setdefault(pages[block.page_id], []).append(
            {
                "text": " ".join((_effective_block_text(block) or block.raw_text or "").split()),
                "box": [round(block.bbox[k], 4) for k in ("x1", "y1", "x2", "y2")],
                "vote": consensus.get("status"),
                "check": status.get(block.id),
                "readings": consensus.get("other_readings") or {},
            }
        )
    return dict(sorted(out.items()))
