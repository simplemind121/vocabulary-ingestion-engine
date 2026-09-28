from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import SourceBlock, SourceEntry, VocabularyEntry
from app.services.benchmark import run_gold_benchmark


def build_run_prediction(db: Session, run_id: str) -> dict[str, list[dict[str, Any]]]:
    blocks = (
        db.query(SourceBlock)
        .filter(SourceBlock.processing_run_id == run_id)
        .order_by(SourceBlock.page_id, SourceBlock.reading_order, SourceBlock.id)
        .all()
    )
    entries = (
        db.query(SourceEntry)
        .filter(SourceEntry.processing_run_id == run_id)
        .order_by(SourceEntry.entry_order, SourceEntry.id)
        .all()
    )
    vocabulary = (
        db.query(VocabularyEntry)
        .filter(VocabularyEntry.processing_run_id == run_id)
        .order_by(VocabularyEntry.lemma, VocabularyEntry.id)
        .all()
    )

    return {
        "blocks": [{"text": _effective_text(block)} for block in blocks],
        "entries": [
            {
                "lemma": entry.vocabulary_entry.lemma if entry.vocabulary_entry is not None else "",
                "raw_text": entry.raw_text,
            }
            for entry in entries
        ],
        "vocabulary": [
            {
                "lemma": item.lemma,
                "display_form": item.display_form,
                "ipa": item.ipa,
                "part_of_speech": item.part_of_speech,
                "definition": item.definition,
            }
            for item in vocabulary
        ],
    }


def benchmark_processing_run(db: Session, run_id: str, ground_truth: dict[str, Any]) -> dict[str, Any]:
    prediction = build_run_prediction(db, run_id)
    result = run_gold_benchmark(prediction, ground_truth)
    result["processing_run_id"] = run_id
    return result


def _effective_text(block: SourceBlock) -> str:
    metadata = block.metadata_json or {}
    review = metadata.get("human_ocr_review") or {}
    reviewed = metadata.get("reviewed_text")
    if reviewed and review.get("decision") == "ACCEPT":
        return str(reviewed)
    return block.raw_text or ""
