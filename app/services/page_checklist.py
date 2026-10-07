"""Per-page headword checklists printed in the source book.

Some vocabulary books print, at the foot of every page, the list of headwords
that start on that page. On a scanned book this is a second, independent
reading of every headword: where it agrees with the headword lines the page is
confirmed, and where it disagrees a human is asked instead of anyone guessing.
The checklist rows themselves are page furniture and never become entry text.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.adapters.pdf_native import PyMuPDFNativeAdapter
from app.models import Page, ProcessingRun, ProcessingStep, ReviewTask, SourceBlock
from app.services.book_structure import classify_book_text
from app.services.segmentation import _effective_block_text

CHECKLIST_ROLE = "HEADWORD_CHECKLIST"
REASON_HEADWORD = "HEADWORD_NOT_IN_CHECKLIST"
REASON_PAGE = "HEADWORD_CHECKLIST_MISMATCH"
REASON_NO_CHECKLIST = "HEADWORD_PAGE_WITHOUT_CHECKLIST"
CHECKLIST_REASONS = (REASON_HEADWORD, REASON_PAGE, REASON_NO_CHECKLIST)
NON_ENTRY_PAGE_ROLE = "NON_ENTRY_PAGE"
PAGE_CLASSIFICATIONS = {
    REASON_PAGE: {"HEADWORD_CHECKLIST_REVIEWED"},
    REASON_NO_CHECKLIST: {"NOT_AN_ENTRY_PAGE", "ENTRY_PAGE_CONFIRMED"},
}
STEP_SEQUENCE = 15
_FOOT = 0.88
_ROW = re.compile(r"[A-Za-z0-9'’\- ]*[A-Za-z][A-Za-z0-9'’\- ]*")
_MIN_PAGES = 5
_MIN_SHARE = 0.3


def _letters(text: str) -> str:
    return re.sub(r"[^a-z'’-]", "", text.lower())


def compare_page(headwords: list[str], checklist_rows: list[str]) -> dict:
    """Match the headword lines of a page against its printed checklist."""
    remainder = _letters("".join(checklist_rows))
    total = len(remainder)
    unexpected: list[str] = []
    # Longest first, so "press" never eats part of "impress".
    for headword in sorted((item.lower() for item in headwords), key=len, reverse=True):
        if headword in remainder:
            remainder = remainder.replace(headword, "", 1)
        else:
            unexpected.append(headword)
    return {
        "agrees": not remainder and not unexpected,
        "unmatched_checklist_text": remainder,
        "headwords_not_in_checklist": [
            item for item in (word.lower() for word in headwords) if item in unexpected
        ],
        "coverage": (total - len(remainder)) / total if total else 0.0,
    }


def apply_headword_checklists(db: Session, run_id: str) -> dict:
    """Mark checklist rows and queue every page whose checklist disagrees."""
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    pages = {
        page.id: page.page_number
        for page in db.query(Page).filter(Page.document_version_id == run.document_version_id)
    }
    by_page: dict[str, list[SourceBlock]] = {}
    for block in (
        db.query(SourceBlock)
        .filter(
            SourceBlock.processing_run_id == run_id,
            SourceBlock.source_engine != PyMuPDFNativeAdapter.name,
        )
        .order_by(SourceBlock.reading_order)
        .all()
    ):
        by_page.setdefault(block.page_id, []).append(block)

    analysed = []
    for page_id, blocks in by_page.items():
        heads, rows = [], []
        for block in blocks:
            # Checklist rows are recognised from the raw reading, so a re-run
            # sees them again after they have been marked as page furniture.
            raw = " ".join((block.raw_text or "").split())
            if float(block.bbox["y1"]) >= _FOOT and _ROW.fullmatch(raw):
                rows.append(block)
                continue
            text = " ".join(_effective_block_text(block).split())
            if not text:
                continue
            classification = classify_book_text(text)
            if classification.block_type == "ENTRY_HEAD":
                heads.append((block, classification.metadata["lemma"]))
        if heads or rows:
            result = compare_page(
                [lemma for _, lemma in heads],
                [" ".join((row.raw_text or "").split()) for row in rows],
            )
            analysed.append((page_id, heads, rows, result))

    with_rows = [item for item in analysed if item[2]]
    confirmed = [item for item in with_rows if item[3]["coverage"] >= 0.5]
    has_checklists = len(confirmed) >= _MIN_PAGES and len(confirmed) >= _MIN_SHARE * len(
        [item for item in analysed if item[1]]
    )
    metrics = {
        "book_has_headword_checklists": has_checklists,
        "pages_with_checklist": 0,
        "pages_without_checklist": 0,
        "pages_agreeing": 0,
        "pages_disagreeing": 0,
        "headwords_confirmed": 0,
        "review_tasks_created": 0,
    }
    if has_checklists:
        for page_id, heads, rows, result in analysed:
            if not rows:
                # Headword-shaped lines on a page the book gave no checklist:
                # a preface sample or a lost footer. A human says which.
                if not _has_task(db, run_id, "Page", page_id, REASON_NO_CHECKLIST):
                    db.add(
                        ReviewTask(
                            processing_run_id=run_id,
                            reason_code=REASON_NO_CHECKLIST,
                            status="OPEN",
                            target_entity_type="Page",
                            target_entity_id=page_id,
                            target_field_path="headword_checklist",
                            source_context={
                                "page_number": pages.get(page_id),
                                "headwords_as_read": [lemma for _, lemma in heads],
                            },
                            candidate_values=[],
                        )
                    )
                    metrics["review_tasks_created"] += 1
                metrics["pages_without_checklist"] += 1
                continue
            metrics["pages_with_checklist"] += 1
            for row in rows:
                if (row.metadata_json or {}).get("role") != CHECKLIST_ROLE:
                    row.metadata_json = {**(row.metadata_json or {}), "role": CHECKLIST_ROLE}
            unexpected = set(result["headwords_not_in_checklist"])
            metrics["headwords_confirmed"] += len(heads) - len(unexpected)
            if result["agrees"]:
                metrics["pages_agreeing"] += 1
                continue
            metrics["pages_disagreeing"] += 1
            metrics["review_tasks_created"] += _queue_reviews(
                db, run_id, page_id, pages.get(page_id), heads, result
            )

    step = (
        db.query(ProcessingStep)
        .filter(
            ProcessingStep.processing_run_id == run_id,
            ProcessingStep.sequence_no == STEP_SEQUENCE,
        )
        .one_or_none()
    )
    if step is None:
        step = ProcessingStep(
            processing_run_id=run_id,
            step_type="HEADWORD_CHECKLIST_VALIDATION",
            sequence_no=STEP_SEQUENCE,
            processor_name="headword-checklist",
            processor_version="1.0.0",
            configuration={"foot_region_from": _FOOT},
            status="COMPLETED",
        )
        db.add(step)
    else:
        step.retry_count += 1
    step.metrics = metrics
    db.commit()
    return {"run_id": run_id, **metrics}


def _queue_reviews(
    db: Session,
    run_id: str,
    page_id: str,
    page_number: int | None,
    heads: list[tuple[SourceBlock, str]],
    result: dict,
) -> int:
    created = 0
    remainder = result["unmatched_checklist_text"]
    unexpected = [
        (block, lemma)
        for block, lemma in heads
        if lemma.lower() in result["headwords_not_in_checklist"]
        # A human has already ruled on this line; their reading stands.
        and not (block.metadata_json or {}).get("human_ocr_review")
    ]
    for block, lemma in unexpected:
        if _has_task(db, run_id, "SourceBlock", block.id, REASON_HEADWORD):
            continue
        candidates = []
        if remainder and SequenceMatcher(None, lemma.lower(), remainder).ratio() >= 0.6:
            # The checklist's own spelling, offered for one-click confirmation.
            text = " ".join(_effective_block_text(block).split())
            candidates.append(remainder + text[len(lemma) :])
        db.add(
            ReviewTask(
                processing_run_id=run_id,
                reason_code=REASON_HEADWORD,
                status="OPEN",
                target_entity_type="SourceBlock",
                target_entity_id=block.id,
                target_field_path="raw_text",
                source_context={
                    "page_number": page_number,
                    "headword_as_read": lemma,
                    "unmatched_checklist_text": remainder,
                },
                candidate_values=candidates,
            )
        )
        created += 1
    if remainder and not unexpected and not _has_task(db, run_id, "Page", page_id, REASON_PAGE):
        # The checklist names a headword no line on the page starts with.
        db.add(
            ReviewTask(
                processing_run_id=run_id,
                reason_code=REASON_PAGE,
                status="OPEN",
                target_entity_type="Page",
                target_entity_id=page_id,
                target_field_path="headword_checklist",
                source_context={
                    "page_number": page_number,
                    "unmatched_checklist_text": remainder,
                    "classification": "HEADWORD_CHECKLIST_REVIEWED",
                },
                candidate_values=[],
            )
        )
        created += 1
    return created


def mark_non_entry_page(db: Session, run_id: str, page_id: str) -> int:
    """A human ruled the page holds no entries: its text stops feeding segmentation."""
    blocks = (
        db.query(SourceBlock)
        .filter(SourceBlock.processing_run_id == run_id, SourceBlock.page_id == page_id)
        .all()
    )
    for block in blocks:
        metadata = dict(block.metadata_json or {})
        metadata.setdefault("role", NON_ENTRY_PAGE_ROLE)
        block.metadata_json = metadata
    return len(blocks)


def _has_task(db: Session, run_id: str, entity_type: str, entity_id: str, reason: str) -> bool:
    return (
        db.query(ReviewTask)
        .filter(
            ReviewTask.processing_run_id == run_id,
            ReviewTask.target_entity_type == entity_type,
            ReviewTask.target_entity_id == entity_id,
            ReviewTask.reason_code == reason,
        )
        .first()
        is not None
    )
