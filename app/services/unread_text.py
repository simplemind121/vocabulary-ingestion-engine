"""Printed text that no line of the run covers.

The primary reader decides where the lines are. A line it never detects (a
speech bubble, a pale or very short line) is never voted on: the other readers'
text for it is dropped with it, and nothing downstream knows the line exists.

A scan's hidden OCR layer, where there is one, reads the page independently,
word by word with positions. Its words that fall outside every line of the run
are text the run has not read. They are routed to review per page and never
become source text by themselves.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Artifact, DocumentVersion, Page, ProcessingRun, ReviewTask, SourceBlock

UNREAD_TEXT = "UNREAD_TEXT"
# Parked like a line the readers dispute: it is reported and reviewed, but a
# stray mark misread as words must not stop a run on its own.
DEFERRED = "DEFERRED"
# A word belongs to a line when its centre lies inside the line's box, give or
# take this share of the page.
_PAD = 0.004
_LETTERS = re.compile(r"[^\W\d_]{2,}")


def find_unread_text(pdf_path: str | Path, page_number: int, line_boxes: list[dict]) -> list[dict]:
    """Rows of the page's own text layer that lie outside every given line box.

    Boxes are page-relative (0 to 1). A row is kept only if it looks like text:
    two or more words with letters, one of them at least three letters long,
    so a lone stray mark read as a letter is not reported.
    """
    import fitz

    with fitz.open(pdf_path) as document:
        if not 0 < page_number <= document.page_count:
            return []
        page = document[page_number - 1]
        width, height = page.rect.width, page.rect.height
        rows: dict[tuple[int, int], list] = {}
        for x1, y1, x2, y2, word, block, line, _ in page.get_text("words"):
            box = (x1 / width, y1 / height, x2 / width, y2 / height)
            if not _covered(box, line_boxes):
                rows.setdefault((block, line), []).append((box, word))
    found = []
    for words in rows.values():
        texts = [word for _, word in words]
        lettered = [match for text in texts for match in _LETTERS.findall(text)]
        if len(lettered) < 2 or not any(len(match) >= 3 for match in lettered):
            continue
        found.append(
            {
                "text": " ".join(texts),
                "x1": round(min(box[0] for box, _ in words), 4),
                "y1": round(min(box[1] for box, _ in words), 4),
                "x2": round(max(box[2] for box, _ in words), 4),
                "y2": round(max(box[3] for box, _ in words), 4),
            }
        )
    return sorted(found, key=lambda row: (row["y1"], row["x1"]))


def _covered(box: tuple[float, float, float, float], line_boxes: list[dict]) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(
        line["x1"] - _PAD <= cx <= line["x2"] + _PAD and line["y1"] - _PAD <= cy <= line["y2"] + _PAD
        for line in line_boxes
    )


def route_unread_text_reviews(db: Session, run_id: str) -> dict:
    """Park one review per page that has text no line of the run covers."""
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    version = db.get(DocumentVersion, run.document_version_id)
    source = db.get(Artifact, version.source_artifact_id) if version is not None else None
    if source is None or not Path(source.object_key).is_file():
        return {"run_id": run_id, "pages_checked": 0, "pages_with_unread_text": 0, "unread_rows": 0}

    pages = db.query(Page).filter(Page.document_version_id == run.document_version_id).order_by(Page.page_number).all()
    boxes: dict[str, list[dict]] = {}
    for block in db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id):
        boxes.setdefault(block.page_id, []).append(block.bbox)
    known = {
        task.target_entity_id
        for task in db.query(ReviewTask).filter(
            ReviewTask.processing_run_id == run_id, ReviewTask.reason_code == UNREAD_TEXT
        )
    }
    flagged = rows_total = 0
    for page in pages:
        rows = find_unread_text(source.object_key, page.page_number, boxes.get(page.id, []))
        if not rows:
            continue
        flagged += 1
        rows_total += len(rows)
        if page.id in known:
            continue
        db.add(
            ReviewTask(
                processing_run_id=run_id,
                reason_code=UNREAD_TEXT,
                status=DEFERRED,
                target_entity_type="Page",
                target_entity_id=page.id,
                source_context={"page_number": page.page_number, "reader": "pdf-text-layer", "rows": rows},
                candidate_values=[],
            )
        )
    db.commit()
    return {
        "run_id": run_id,
        "pages_checked": len(pages),
        "pages_with_unread_text": flagged,
        "unread_rows": rows_total,
    }
