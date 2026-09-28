from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Definition, Pronunciation, ReviewTask, Sense, VocabularyEntry

_VERIFIED = {"AUTO_VERIFIED", "HUMAN_VERIFIED"}


def build_gold_dataset(db: Session, run_id: str) -> dict:
    entries = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id).order_by(VocabularyEntry.lemma).all()
    unresolved = [entry.id for entry in entries if entry.verification_status not in _VERIFIED]
    open_reviews = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"])).count()
    if not entries:
        raise ValueError("cannot publish empty gold dataset")
    if unresolved:
        raise ValueError(f"cannot publish gold dataset with unresolved entries: {len(unresolved)}")
    if open_reviews:
        raise ValueError(f"cannot publish gold dataset with open review tasks: {open_reviews}")

    records = []
    for entry in entries:
        pronunciations = db.query(Pronunciation).filter(Pronunciation.vocabulary_entry_id == entry.id).order_by(Pronunciation.pronunciation_order).all()
        senses = db.query(Sense).filter(Sense.vocabulary_entry_id == entry.id).order_by(Sense.sense_order).all()
        sense_records = []
        for sense in senses:
            definitions = db.query(Definition).filter(Definition.sense_id == sense.id).order_by(Definition.definition_order).all()
            sense_records.append({"part_of_speech": sense.part_of_speech, "definitions": [definition.text for definition in definitions]})
        records.append({"id": entry.id, "lemma": entry.lemma, "language": entry.language, "verification_status": entry.verification_status, "pronunciations": [{"ipa": p.ipa, "dialect": p.dialect} for p in pronunciations], "senses": sense_records})

    return {"schema_version": "1.0", "processing_run_id": run_id, "record_count": len(records), "records": records}
