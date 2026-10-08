from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import (
    Definition,
    Pronunciation,
    ProvenanceRecord,
    ReviewTask,
    Sense,
    SourceEntry,
    SourceEntryBlock,
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
    unconfirmed_entries = 0
    parked = {
        task.target_entity_id
        for task in db.query(ReviewTask).filter(
            ReviewTask.processing_run_id == run_id,
            ReviewTask.target_entity_type == "SourceBlock",
            ReviewTask.status == "DEFERRED",
        )
    }
    unconfirmed_rows: dict[str, int] = {}
    if parked:
        for link in (
            db.query(SourceEntryBlock)
            .join(SourceEntry, SourceEntry.id == SourceEntryBlock.source_entry_id)
            .filter(SourceEntry.processing_run_id == run_id)
        ):
            if link.source_block_id in parked:
                unconfirmed_rows[link.source_entry_id] = (
                    unconfirmed_rows.get(link.source_entry_id, 0) + 1
                )

    for entry in entries:
        issues: list[dict] = []
        if not entry.lemma or not _LEMMA.fullmatch(entry.lemma.strip()):
            issues.append({"code": "INVALID_LEMMA", "field": "lemma", "value": entry.lemma})
        elif not _has_source_provenance(db, run_id, "VocabularyEntry", entry.id, "lemma"):
            issues.append({"code": "MISSING_LEMMA_PROVENANCE", "field": "lemma", "value": entry.lemma})

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
            elif (
                pronunciation.ipa
                # A dictionary-supplied pronunciation is enrichment by label; it
                # is not expected to trace back to the printed page.
                and pronunciation.verification_status != "DICTIONARY_ONLY"
                and not _has_source_provenance(
                    db, run_id, "Pronunciation", pronunciation.id, "ipa"
                )
            ):
                issues.append(
                    {"code": "MISSING_IPA_PROVENANCE", "field": "pronunciation.ipa", "value": pronunciation.ipa}
                )
            elif pronunciation.verification_status not in {
                "HUMAN_VERIFIED",
                # Recovered through a dictionary, not read directly: keeps its label.
                "DICTIONARY_CORROBORATED",
                "DICTIONARY_ONLY",
            }:
                pronunciation.verification_status = "AUTO_VERIFIED"

        senses = db.query(Sense).filter(Sense.vocabulary_entry_id == entry.id).all()
        if not senses:
            issues.append({"code": "MISSING_SENSE", "field": "senses", "value": None})
        for sense in senses:
            if sense.part_of_speech and not _has_source_provenance(
                db, run_id, "Sense", sense.id, "part_of_speech"
            ):
                issues.append(
                    {
                        "code": "MISSING_POS_PROVENANCE",
                        "field": "sense.part_of_speech",
                        "value": sense.part_of_speech,
                    }
                )
            elif sense.verification_status != "HUMAN_VERIFIED":
                sense.verification_status = "AUTO_VERIFIED"

            definitions = db.query(Definition).filter(Definition.sense_id == sense.id).all()
            for definition in definitions:
                if not _has_source_provenance(db, run_id, "Definition", definition.id, "text"):
                    issues.append(
                        {
                            "code": "MISSING_DEFINITION_PROVENANCE",
                            "field": "definition.text",
                            "value": definition.text,
                        }
                    )
                elif definition.verification_status != "HUMAN_VERIFIED":
                    definition.verification_status = "AUTO_VERIFIED"

        source_fields = (
            db.query(VocabularyField)
            .filter(VocabularyField.vocabulary_entry_id == entry.id)
            .all()
        )
        for source_field in source_fields:
            if not _has_source_provenance(db, run_id, "VocabularyField", source_field.id, "text"):
                issues.append(
                    {
                        "code": "MISSING_FIELD_PROVENANCE",
                        "field": f"source_field.{source_field.field_type}",
                        "value": source_field.text,
                    }
                )
            elif source_field.verification_status != "HUMAN_VERIFIED":
                source_field.verification_status = "AUTO_VERIFIED"

        unconfirmed = unconfirmed_rows.get(entry.source_entry_id, 0)
        metadata = dict(entry.metadata_json or {})
        if metadata.get("unconfirmed_ocr_rows", 0) != unconfirmed:
            metadata["unconfirmed_ocr_rows"] = unconfirmed
            entry.metadata_json = metadata
        if issues:
            entry.verification_status = "REVIEW_REQUIRED"
            issue_count += len(issues)
            _ensure_review_task(db, run_id, entry, issues)
        elif unconfirmed:
            # Its text rests on lines no second reader confirmed. The parked
            # line reviews already track them; the entry simply waits.
            if entry.verification_status != "HUMAN_VERIFIED":
                entry.verification_status = "REVIEW_REQUIRED"
            unconfirmed_entries += 1
        elif entry.verification_status != "HUMAN_VERIFIED":
            entry.verification_status = "AUTO_VERIFIED"
            clean_count += 1

    db.commit()
    return {
        "run_id": run_id,
        "entry_count": len(entries),
        "clean_entries": clean_count,
        "validation_issues": issue_count,
        "entries_awaiting_ocr_confirmation": unconfirmed_entries,
    }


def _has_source_provenance(
    db: Session,
    run_id: str,
    entity_type: str,
    entity_id: str,
    field_path: str,
) -> bool:
    provenance = (
        db.query(ProvenanceRecord)
        .filter(
            ProvenanceRecord.processing_run_id == run_id,
            ProvenanceRecord.target_entity_type == entity_type,
            ProvenanceRecord.target_entity_id == entity_id,
            ProvenanceRecord.target_field_path == field_path,
            ProvenanceRecord.provenance_type.like("SOURCE_%"),
        )
        .first()
    )
    return bool(
        provenance is not None
        and provenance.source_entry_id is not None
        and provenance.page_id is not None
    )


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
