from __future__ import annotations

import csv
import hashlib
import io
import json

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Definition, GoldRelease, Pronunciation, ReviewTask, Sense, VocabularyEntry

_VERIFIED = {"AUTO_VERIFIED", "HUMAN_VERIFIED"}


def build_gold_dataset(db: Session, run_id: str) -> dict:
    entries = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id).order_by(VocabularyEntry.lemma, VocabularyEntry.id).all()
    unresolved = [entry.id for entry in entries if entry.verification_status not in _VERIFIED]
    open_reviews = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"])).count()
    if not entries: raise ValueError("cannot publish empty gold dataset")
    if unresolved: raise ValueError(f"cannot publish gold dataset with unresolved entries: {len(unresolved)}")
    if open_reviews: raise ValueError(f"cannot publish gold dataset with open review tasks: {open_reviews}")
    records = []
    for entry in entries:
        pronunciations = db.query(Pronunciation).filter(Pronunciation.vocabulary_entry_id == entry.id).order_by(Pronunciation.pronunciation_order).all()
        senses = db.query(Sense).filter(Sense.vocabulary_entry_id == entry.id).order_by(Sense.sense_order).all(); sense_records = []
        for sense in senses:
            definitions = db.query(Definition).filter(Definition.sense_id == sense.id).order_by(Definition.definition_order).all()
            sense_records.append({"part_of_speech": sense.part_of_speech, "definitions": [d.text for d in definitions]})
        records.append({"id": entry.id, "lemma": entry.lemma, "language": entry.language, "verification_status": entry.verification_status, "pronunciations": [{"ipa": p.ipa, "dialect": p.dialect} for p in pronunciations], "senses": sense_records})
    return {"schema_version": "1.0", "processing_run_id": run_id, "record_count": len(records), "records": records}


def serialize_gold_json(dataset: dict) -> bytes:
    return json.dumps(dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def serialize_gold_csv(dataset: dict) -> bytes:
    output = io.StringIO(newline=""); writer = csv.writer(output); writer.writerow(["id", "lemma", "language", "verification_status", "ipa", "part_of_speech", "definitions"])
    for record in dataset["records"]:
        ipa = " | ".join(p["ipa"] or "" for p in record["pronunciations"])
        pos = " | ".join(s["part_of_speech"] or "" for s in record["senses"])
        definitions = " | ".join(d for s in record["senses"] for d in s["definitions"])
        writer.writerow([record["id"], record["lemma"], record["language"], record["verification_status"], ipa, pos, definitions])
    return output.getvalue().encode("utf-8")


def publish_gold_release(db: Session, run_id: str) -> GoldRelease:
    dataset = build_gold_dataset(db, run_id); payload = serialize_gold_json(dataset); digest = hashlib.sha256(payload).hexdigest()
    existing = db.query(GoldRelease).filter(GoldRelease.sha256 == digest).one_or_none()
    if existing is not None: return existing
    version = (db.query(func.max(GoldRelease.version)).filter(GoldRelease.processing_run_id == run_id).scalar() or 0) + 1
    release = GoldRelease(processing_run_id=run_id, version=version, schema_version=dataset["schema_version"], record_count=dataset["record_count"], sha256=digest)
    db.add(release); db.commit(); db.refresh(release); return release
