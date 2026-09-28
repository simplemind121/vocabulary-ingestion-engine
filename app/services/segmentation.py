from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import (
    DocumentVersion,
    ProcessingRun,
    ProcessingStep,
    SourceBlock,
    SourceEntry,
    SourceEntryBlock,
    VocabularyEntry,
)

_HEADWORD = re.compile(r"^([A-Za-z][A-Za-z'’-]{1,63})(?:\s|$)")


@dataclass(slots=True)
class SegmentCandidate:
    lemma: str
    raw_text: str
    block_ids: list[str]
    confidence: float


def _candidate_from_block(block: SourceBlock) -> SegmentCandidate | None:
    text = " ".join((block.raw_text or "").split())
    if not text:
        return None
    match = _HEADWORD.match(text)
    if not match:
        return None
    lemma = match.group(1)
    return SegmentCandidate(
        lemma=lemma,
        raw_text=text,
        block_ids=[block.id],
        confidence=0.80,
    )


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
    if existing:
        return {
            "run_id": run.id,
            "source_entries": len(existing),
            "reused": True,
        }

    version = db.get(DocumentVersion, run.document_version_id)
    if version is None:
        raise ValueError("document version not found")

    blocks = (
        db.query(SourceBlock)
        .filter(SourceBlock.processing_run_id == run.id)
        .order_by(SourceBlock.page_id, SourceBlock.reading_order)
        .all()
    )

    step = ProcessingStep(
        processing_run_id=run.id,
        step_type="ENTRY_SEGMENTATION",
        sequence_no=20,
        processor_name="baseline-rule-segmenter",
        processor_version="0.1.0",
        configuration={"strategy": "headword-at-block-start"},
        status="RUNNING",
    )
    db.add(step)
    db.flush()

    candidates = [candidate for block in blocks if (candidate := _candidate_from_block(block))]

    for index, candidate in enumerate(candidates, start=1):
        entry = SourceEntry(
            document_version_id=version.id,
            processing_run_id=run.id,
            entry_order=index,
            raw_text=candidate.raw_text,
            segmentation_confidence=candidate.confidence,
            status="PARSED",
            metadata_json={"segmenter": "baseline-rule-segmenter"},
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
                metadata_json={"extraction_method": "baseline-rule"},
            )
        )

    step.status = "COMPLETED"
    step.metrics = {
        "input_blocks": len(blocks),
        "source_entries": len(candidates),
    }
    db.commit()
    return {
        "run_id": run.id,
        "source_entries": len(candidates),
        "reused": False,
    }
