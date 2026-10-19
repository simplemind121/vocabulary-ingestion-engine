"""Lines the primary reader never detected, read again and added to the page.

``find_unread_text`` reports rows of the scan's hidden text layer that lie outside
every line of the run. Each such row is a proposed line: its part of the page is
rendered on its own and given to the line reader again. The two readings (the
reader's, from the crop, and the text layer's) are voted like any other line:

- agreed: the line joins the page in reading order, as a normal line;
- not agreed: the line still joins the page, with both readings and a low
  confidence, so the readers-disagree review takes it up as for any line.

A row the reader finds nothing in stays unread and keeps its UNREAD_TEXT review.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.adapters.ocr_base import OcrPageInput
from app.models import Page, ProcessingRun, SourceBlock
from app.services.ocr_consensus import DISPUTED, SINGLE_READER, build_consensus
from app.services.unread_text import find_unread_text
from app.structure.store import source_pdf

# How much of the page around the row is rendered for the second reading
# (wider than tall: a line's neighbours above and below must stay out).
_MARGIN_X = 0.01
_MARGIN_Y = 0.004
_ZOOM = 3.0
_UNCONFIRMED_CONFIDENCE = 0.5
RECOVERED = "recovered"


def _crop(pdf_path: str, page_number: int, row: dict) -> bytes:
    import fitz

    with fitz.open(pdf_path) as document:
        page = document[page_number - 1]
        w, h = page.rect.width, page.rect.height
        clip = fitz.Rect(*(v * s for v, s in zip(_crop_box(row), (w, h, w, h), strict=True)))
        return page.get_pixmap(clip=clip, matrix=fitz.Matrix(_ZOOM, _ZOOM), alpha=False).tobytes("png")


def _crop_box(row: dict) -> tuple[float, float, float, float]:
    return (
        max(row["x1"] - _MARGIN_X, 0),
        max(row["y1"] - _MARGIN_Y, 0),
        min(row["x2"] + _MARGIN_X, 1),
        min(row["y2"] + _MARGIN_Y, 1),
    )


def _on_the_row(blocks: list, row: dict) -> list:
    """The crop's lines whose middle lies within the row's own band: the edges of neighbouring lines are dropped."""
    _, y1, _, y2 = _crop_box(row)
    top, bottom = (row["y1"] - y1) / (y2 - y1), (row["y2"] - y1) / (y2 - y1)
    return [b for b in blocks if top <= (b.bbox.y1 + b.bbox.y2) / 2 <= bottom]


def _place(blocks: list[SourceBlock], row: dict) -> int:
    """Index in reading order after which the row belongs.

    After the last line above it in the same column; failing that, after the
    last line above it anywhere; failing that, first on the page.
    """
    above = [i for i, block in enumerate(blocks) if block.bbox["y1"] <= row["y1"]]
    column = [i for i in above if min(blocks[i].bbox["x2"], row["x2"]) - max(blocks[i].bbox["x1"], row["x1"]) > 0]
    return max(column or above or [-1])


def recover_unread_lines(db: Session, run_id: str, adapter) -> dict:
    """Read every unread row again with ``adapter`` and add it to its page."""
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    pdf = source_pdf(db, run_id)
    if pdf is None:
        return {"run_id": run_id, "rows": 0, "recovered": 0, "confirmed": 0, "unreadable": 0}
    pages = db.query(Page).filter(Page.document_version_id == run.document_version_id).order_by(Page.page_number).all()
    rows_total = recovered = confirmed = unreadable = 0
    for page in pages:
        blocks = (
            db.query(SourceBlock)
            .filter(SourceBlock.processing_run_id == run_id, SourceBlock.page_id == page.id)
            .order_by(SourceBlock.reading_order)
            .all()
        )
        rows = find_unread_text(pdf, page.page_number, [block.bbox for block in blocks])
        if not rows:
            continue
        rows_total += len(rows)
        for row in rows:
            # Page number 0: readers keyed by page (imported readings, the text
            # layer) must not answer for a crop with their whole page.
            result = adapter.extract_page(OcrPageInput(page_number=0, image_bytes=_crop(pdf, page.page_number, row)))
            mine = _on_the_row(result.blocks, row)
            reading = " ".join(block.text.strip() for block in sorted(mine, key=lambda b: b.reading_order) if block.text.strip())
            if not reading:
                unreadable += 1
                continue
            consensus = build_consensus(reading, [row["text"]])
            agreed = consensus.status not in {DISPUTED, SINGLE_READER}
            confirmed += agreed
            confidences = [b.confidence for b in mine if b.confidence is not None]
            confidence = min(confidences) if confidences else None
            block = SourceBlock(
                page_id=page.id,
                processing_run_id=run_id,
                block_type="TEXT",
                raw_text=consensus.text,
                confidence=confidence if agreed else min(confidence or 0.0, _UNCONFIRMED_CONFIDENCE),
                bbox={"x1": row["x1"], "y1": row["y1"], "x2": row["x2"], "y2": row["y2"], "unit": "page"},
                source_engine=f"ocr:{result.engine_name}",
                source_engine_version=result.engine_version,
                metadata_json={
                    RECOVERED: {"from": "pdf-text-layer", "text_layer": row["text"], "reread": reading},
                    "consensus": {
                        "status": consensus.status,
                        "readers": consensus.readers,
                        "corrections": consensus.corrections,
                        "disputes": consensus.disputes,
                        "primary_text": reading,
                        "primary_confidence": confidence,
                        "other_readings": {"pdf-text-layer": row["text"]},
                    },
                },
            )
            blocks.insert(_place(blocks, row) + 1, block)
            db.add(block)
            recovered += 1
        # Reading order is renumbered so the new lines sit where they are printed.
        for order, block in enumerate(blocks):
            block.reading_order = order
        db.commit()
    return {"run_id": run_id, "rows": rows_total, "recovered": recovered, "confirmed": confirmed, "unreadable": unreadable}
