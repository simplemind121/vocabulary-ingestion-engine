from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import (
    Pronunciation,
    ProvenanceRecord,
    ReviewTask,
    Sense,
    VocabularyEntry,
    VocabularyField,
)

_LEMMA = re.compile(r"^[A-Za-z][A-Za-z'’-]{0,511}$")
_IPA_FORBIDDEN = re.compile(r"[0-9<>={}\\]")


def validate_canonical_entries(db: Session, run_id: str) -> dict:
    entries = (
        db.query(VocabularyEntry)
        .filter(VocabularyEntry.processing_run_id == run_id)
        .all()
    )
    issue_count = 0
    clean_count = 0

    for entry in entries:
        issues: list[dict] = []
        if not entry.lemma or not _LEMMA.fullmatch(entry.lemma.strip()):
            issues.append({"code": "INVALID_LEMMA", "field": "lemma", "value": entry.lemma})

        pronunciations = (
            db.query(Pronunciation)
            .filter(Pronunciation.vocabulary_entry_id == entry.id)
            .all()
        )
        for pronunciation in pronunciations:
            if pronunciation.ipa and _IPA_FORBIDDEN.search(pronunciation.ipa):
                issues.append(
                    {"code": "INVALID_IPA", "field": "pronunciation.ipa", "value": pronunciation.ipa}
                )

        senses = db.query(Sense).filter(Sense.vocabulary_entry_id == entry.id).all()
        if not senses:
            issues.append({"code": "MISSING_SENSE", "field": "senses", "value": None})

        source_fields = (
            db.query(VocabularyField)
            .filter(VocabularyField.vocabulary_entry_id == entry.id)
            .all()
        )
        for source_field in source_fields:
            provenance = (
                db.query(ProvenanceRecord)
                .filter(
                    ProvenanceRecord.processing_run_id == run_id,
                    ProvenanceRecord.target_entity_type == "VocabularyField",
                    ProvenanceRecord.target_entity_id == source_field.id,
                    ProvenanceRecord.target_field_path == "text",
                    ProvenanceRecord.provenance_type.like("SOURCE_%"),
                )
                .first()
            )
            if provenance is None or provenance.source_entry_id is None or provenance.page_id is None:
                issues.append(
                    {
                        "code": "MISSING_FIELD_PROVENANCE",
                        "field": f"source_field.{source_field.field_type}",
                        "value": source_field.text,
                    }
                )
            elif source_field.verification_status != "HUMAN_VERIFIED":
                source_field.verification_status = "AUTO_VERIFIED"

        if issues:
            entry.verification_status = "REVIEW_REQUIRED"
            issue_count += len(issues)
            _ensure_review_task(db, run_id, entry, issues)
        elif entry.verification_status != "HUMAN_VERIFIED":
            entry.verification_status = "AUTO_VERIFIED"
            clean_count += 1

    db.commit()
    return {
        "run_id": run_id,
        "entry_count": len(entries),
        "clean_entries": clean_count,
        "validation_issues": issue_count,
    }


def _ensure_review_task(db: Session, run_id: str, entry: VocabularyEntry, issues: list[dict]) -> None:
    existing = (
        db.query(ReviewTask)
        .filter(
            ReviewTask.processing_run_id == run_id,
            ReviewTask.target_entity_type == "VocabularyEntry",
            ReviewTask.target_entity_id == entry.id,
            ReviewTask.reason_code == "G4_VALIDATION_FAILED",
            ReviewTask.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"]),
        )
        .first()
    )
    if existing is None:
        db.add(
            ReviewTask(
                processing_run_id=run_id,
                reason_code="G4_VALIDATION_FAILED",
                status="OPEN",
                target_entity_type="VocabularyEntry",
                target_entity_id=entry.id,
                source_context={"issues": issues},
                candidate_values=[],
            )
        )
    else:
        existing.source_context = {"issues": issues}
