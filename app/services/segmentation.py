from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import (
    Definition,
    DocumentVersion,
    Example,
    Page,
    ProcessingRun,
    ProcessingStep,
    Pronunciation,
    ProvenanceRecord,
    ReviewTask,
    Sense,
    SourceBlock,
    SourceEntry,
    SourceEntryBlock,
    SourceMedia,
    VocabularyEntry,
    VocabularyField,
)
from app.services.book_structure import (
    BookBlockClassification,
    bare_headword,
    classify_book_text,
)

_LEGACY_HEADWORD = re.compile(r"^([A-Za-z][A-Za-z'’-]{1,63})(?:\s|$)")


@dataclass(slots=True)
class SegmentCandidate:
    lemma: str
    raw_text: str
    block_ids: list[str]
    confidence: float
    page_numbers: list[int] = field(default_factory=list)
    word_list: int | None = None
    section: str | None = None
    starred: bool = False


# Page furniture recognised upstream (e.g. the per-page headword checklist).
_NON_ENTRY_ROLES = {"HEADWORD_CHECKLIST", "NON_ENTRY_PAGE", "RUNNING_HEADER"}


def _effective_block_text(block: SourceBlock) -> str:
    metadata = getattr(block, "metadata_json", None) or {}
    reviewed_text = metadata.get("reviewed_text")
    review = metadata.get("human_ocr_review") or {}
    if review.get("decision") == "DISCARD" or metadata.get("role") in _NON_ENTRY_ROLES:
        return ""
    if reviewed_text and review.get("decision") == "ACCEPT":
        return str(reviewed_text)
    return getattr(block, "raw_text", "") or ""


def _iter_lines(block: SourceBlock) -> list[str]:
    return [line.strip() for line in _effective_block_text(block).splitlines() if line.strip()]


def _bold_lines(block: SourceBlock) -> set[str]:
    metadata = getattr(block, "metadata_json", None) or {}
    return set(metadata.get("bold_lines") or [])


def _segment_blocks(blocks: list[SourceBlock], page_numbers: dict[str, int]) -> list[SegmentCandidate]:
    candidates: list[SegmentCandidate] = []
    current_lines: list[str] = []
    current_blocks: list[str] = []
    current_pages: list[int] = []
    current_lemma: str | None = None
    current_starred = False
    current_confidence = 0.0
    current_word_list: int | None = None
    in_preview_table = False
    in_non_entry_section = False
    current_section: str | None = None
    has_structured_headwords = any(
        classify_book_text(line).block_type == "ENTRY_HEAD"
        for block in blocks
        for line in _iter_lines(block)
    )

    def flush() -> None:
        nonlocal current_lines, current_blocks, current_pages
        nonlocal current_lemma, current_starred, current_confidence
        if current_lemma and current_lines:
            candidates.append(
                SegmentCandidate(
                    lemma=current_lemma,
                    raw_text="\n".join(current_lines),
                    block_ids=list(dict.fromkeys(current_blocks)),
                    confidence=current_confidence,
                    page_numbers=list(dict.fromkeys(current_pages)),
                    word_list=current_word_list,
                    section=current_section,
                    starred=current_starred,
                )
            )
        current_lines = []
        current_blocks = []
        current_pages = []
        current_lemma = None
        current_starred = False
        current_confidence = 0.0

    for block in blocks:
        page_number = page_numbers.get(block.page_id)
        bold_lines = _bold_lines(block)
        for line in _iter_lines(block):
            classification = classify_book_text(line, in_preview_table=in_preview_table)
            bare = (
                bare_headword(line)
                if " ".join(line.split()) in bold_lines
                and classification.block_type in {"BODY_TEXT", "PREVIEW_TABLE"}
                else None
            )
            if bare is not None:
                # Bold headword on its own line: IPA/POS follow on later lines.
                classification = BookBlockClassification(
                    "ENTRY_HEAD", 0.97, {"lemma": bare[0], "starred": bare[1], "ipa": None}
                )
            if classification.block_type == "WORD_LIST_HEADER":
                if classification.metadata["word_list"] == current_word_list:
                    # Running header repeated on every page: the entry in
                    # progress simply continues underneath it.
                    continue
                flush()
                current_word_list = classification.metadata["word_list"]
                in_preview_table = False
                in_non_entry_section = False
                continue
            if classification.block_type == "ENTRY_SECTION_HEADER":
                if classification.metadata["section"] != current_section:
                    flush()
                    current_section = classification.metadata["section"]
                    current_word_list = None
                    in_preview_table = False
                    in_non_entry_section = False
                continue
            if classification.block_type == "NON_ENTRY_SECTION_HEADER":
                flush()
                in_preview_table = False
                in_non_entry_section = True
                continue
            if in_non_entry_section:
                continue
            if classification.block_type == "PREVIEW_TABLE_HEADER":
                flush()
                in_preview_table = True
                continue
            if in_preview_table:
                if classification.block_type == "ENTRY_HEAD":
                    in_preview_table = False
                else:
                    continue
            if classification.block_type in {"PAGE_NUMBER", "DECORATION", "EMPTY"}:
                continue
            if classification.block_type == "ENTRY_HEAD":
                flush()
                current_lemma = classification.metadata["lemma"]
                current_starred = classification.metadata["starred"]
                current_confidence = classification.confidence
                current_lines = [line]
                current_blocks = [block.id]
                if page_number is not None:
                    current_pages = [page_number]
                continue

            if current_lemma:
                current_lines.append(line)
                current_blocks.append(block.id)
                if page_number is not None:
                    current_pages.append(page_number)
                continue

            legacy = None if has_structured_headwords else _LEGACY_HEADWORD.match(" ".join(line.split()))
            if legacy:
                flush()
                current_lemma = legacy.group(1)
                current_confidence = 0.80
                current_lines = [line]
                current_blocks = [block.id]
                if page_number is not None:
                    current_pages = [page_number]

    flush()
    return candidates


def segment_source_entries(db: Session, run_id: str) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")

    existing = (
        db.query(SourceEntry)
        .filter(SourceEntry.processing_run_id == run.id)
        .order_by(SourceEntry.entry_order)
        .all()
    )
    version = db.get(DocumentVersion, run.document_version_id)
    if version is None:
        raise ValueError("document version not found")

    pages = (
        db.query(Page)
        .filter(Page.document_version_id == version.id)
        .order_by(Page.page_number)
        .all()
    )
    page_numbers = {page.id: page.page_number for page in pages}
    page_order = {page.id: index for index, page in enumerate(pages)}
    blocks = db.query(SourceBlock).filter(SourceBlock.processing_run_id == run.id).all()
    blocks.sort(key=lambda block: (page_order.get(block.page_id, 10**9), block.reading_order or 0))

    fingerprint = _blocks_fingerprint(blocks)
    step = (
        db.query(ProcessingStep)
        .filter(ProcessingStep.processing_run_id == run.id, ProcessingStep.sequence_no == 20)
        .one_or_none()
    )
    rebuilt = False
    if existing:
        recorded = (step.metrics or {}).get("blocks_fingerprint") if step is not None else None
        if recorded is None or recorded == fingerprint:
            return {"run_id": run.id, "source_entries": len(existing), "reused": True}
        # The text the entries were cut from has since been corrected (a review
        # or an arbitration changed a line): everything derived from it is redone.
        discard_derived_entries(db, run.id)
        rebuilt = True
    if step is not None:
        db.delete(step)
        db.flush()

    step = ProcessingStep(
        processing_run_id=run.id,
        step_type="ENTRY_SEGMENTATION",
        sequence_no=20,
        processor_name="book-structure-segmenter",
        processor_version="0.4.0",
        configuration={
            "strategy": "line-state-machine",
            "cross_page": True,
            "reviewed_ocr_precedence": True,
        },
        status="RUNNING",
    )
    db.add(step)
    db.flush()

    candidates = _segment_blocks(blocks, page_numbers)
    cross_page_entries = 0
    for index, candidate in enumerate(candidates, start=1):
        if len(candidate.page_numbers) > 1:
            cross_page_entries += 1
        entry = SourceEntry(
            document_version_id=version.id,
            processing_run_id=run.id,
            entry_order=index,
            raw_text=candidate.raw_text,
            segmentation_confidence=candidate.confidence,
            continuation_type="CROSS_PAGE" if len(candidate.page_numbers) > 1 else None,
            status="PARSED",
            metadata_json={
                "segmenter": "book-structure-segmenter@0.4.0",
                "pages": candidate.page_numbers,
                "word_list": candidate.word_list,
                "section": candidate.section,
                "starred": candidate.starred,
            },
        )
        db.add(entry)
        db.flush()

        for block_order, block_id in enumerate(candidate.block_ids, start=1):
            db.add(
                SourceEntryBlock(
                    source_entry_id=entry.id,
                    source_block_id=block_id,
                    block_order=block_order,
                )
            )

        db.add(
            VocabularyEntry(
                source_entry_id=entry.id,
                processing_run_id=run.id,
                lemma=candidate.lemma,
                display_form=candidate.lemma,
                language="en",
                verification_status="PARSED",
                canonical_schema_version="1.0",
                metadata_json={
                    "extraction_method": "book-structure-segmenter@0.4.0",
                    "starred": candidate.starred,
                    "word_list": candidate.word_list,
                },
            )
        )

    step.status = "COMPLETED"
    step.metrics = {
        "input_blocks": len(blocks),
        "source_entries": len(candidates),
        "cross_page_entries": cross_page_entries,
        "blocks_fingerprint": fingerprint,
    }
    db.commit()
    return {
        "run_id": run.id,
        "source_entries": len(candidates),
        "cross_page_entries": cross_page_entries,
        "reused": False,
        "rebuilt": rebuilt,
    }


def _blocks_fingerprint(blocks: list[SourceBlock]) -> str:
    """Identity of the text entries are cut from, including every correction."""
    digest = hashlib.sha256()
    for block in blocks:
        digest.update(block.id.encode())
        digest.update(b"\0")
        digest.update(_effective_block_text(block).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def discard_derived_entries(db: Session, run_id: str) -> None:
    """Remove everything built on top of the run's blocks so it can be rebuilt.

    Blocks, their reviews and stored media files are source evidence and stay.
    A human verification of an entry or of a media association is not derived
    data, so its presence stops the rebuild instead of being thrown away.
    """
    entries = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id).all()
    if any(entry.verification_status == "HUMAN_VERIFIED" for entry in entries):
        raise ValueError("cannot rebuild entries: human-verified vocabulary entries exist")
    media = (
        db.query(SourceMedia)
        .filter(SourceMedia.processing_run_id == run_id, SourceMedia.source_entry_id.isnot(None))
        .all()
    )
    if any(item.verification_status == "HUMAN_VERIFIED" for item in media):
        raise ValueError("cannot rebuild entries: human-verified media associations exist")

    entry_ids = [entry.id for entry in entries]
    sense_ids = [
        row.id for row in db.query(Sense.id).filter(Sense.vocabulary_entry_id.in_(entry_ids))
    ]
    db.query(ProvenanceRecord).filter(
        ProvenanceRecord.processing_run_id == run_id,
        ProvenanceRecord.target_entity_type.in_(
            ["VocabularyEntry", "Pronunciation", "Sense", "Definition", "Example", "VocabularyField"]
        ),
    ).delete(synchronize_session=False)
    for item in media:
        # Layout associations are recomputed by the media stage against the new entries.
        db.query(ProvenanceRecord).filter(
            ProvenanceRecord.target_entity_type == "SourceMedia",
            ProvenanceRecord.target_entity_id == item.id,
        ).delete(synchronize_session=False)
        db.query(ReviewTask).filter(
            ReviewTask.target_entity_type == "SourceMedia", ReviewTask.target_entity_id == item.id
        ).delete(synchronize_session=False)
        db.delete(item)
    db.query(ReviewTask).filter(
        ReviewTask.processing_run_id == run_id,
        ReviewTask.target_entity_type == "VocabularyEntry",
    ).delete(synchronize_session=False)
    db.query(Definition).filter(Definition.sense_id.in_(sense_ids)).delete(
        synchronize_session=False
    )
    db.query(Example).filter(Example.sense_id.in_(sense_ids)).delete(synchronize_session=False)
    for model in (Sense, Pronunciation, VocabularyField):
        db.query(model).filter(model.vocabulary_entry_id.in_(entry_ids)).delete(
            synchronize_session=False
        )
    db.query(VocabularyEntry).filter(VocabularyEntry.id.in_(entry_ids)).delete(
        synchronize_session=False
    )
    source_ids = [
        row.id
        for row in db.query(SourceEntry.id).filter(SourceEntry.processing_run_id == run_id)
    ]
    db.query(SourceEntryBlock).filter(SourceEntryBlock.source_entry_id.in_(source_ids)).delete(
        synchronize_session=False
    )
    db.query(SourceEntry).filter(SourceEntry.id.in_(source_ids)).delete(
        synchronize_session=False
    )
    db.flush()
