from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime

from openpyxl import Workbook
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Artifact,
    Definition,
    GoldRelease,
    Pronunciation,
    ReviewTask,
    Sense,
    VocabularyEntry,
)
from app.settings import get_settings
from app.storage import StorageAdapter, build_storage_adapter

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


def serialize_gold_xlsx(dataset: dict) -> bytes:
    output = io.BytesIO()
    workbook = Workbook(write_only=True)
    workbook.properties.created = datetime(1980, 1, 1, tzinfo=UTC)
    workbook.properties.modified = datetime(1980, 1, 1, tzinfo=UTC)
    sheet = workbook.create_sheet("Verified Gold")
    sheet.append(
        [
            "id",
            "lemma",
            "language",
            "verification_status",
            "ipa",
            "part_of_speech",
            "definitions",
        ]
    )
    for record in dataset["records"]:
        sheet.append(
            [
                record["id"],
                record["lemma"],
                record["language"],
                record["verification_status"],
                " | ".join(item["ipa"] or "" for item in record["pronunciations"]),
                " | ".join(item["part_of_speech"] or "" for item in record["senses"]),
                " | ".join(
                    definition
                    for sense in record["senses"]
                    for definition in sense["definitions"]
                ),
            ]
        )
    workbook.save(output)
    return _normalize_zip(output.getvalue())


def _normalize_zip(payload: bytes) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(payload), "r")
    output = io.BytesIO()
    with source, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            target.writestr(info, source.read(name))
    return output.getvalue()


def _persist_artifact(db: Session, storage: StorageAdapter, key: str, payload: bytes, artifact_type: str, mime_type: str) -> Artifact:
    existing = db.query(Artifact).filter(Artifact.object_key == key).one_or_none()
    digest = hashlib.sha256(payload).hexdigest()
    if existing is not None:
        if existing.sha256 != digest:
            raise ValueError(f"immutable artifact collision at {key}")
        return existing
    stored = storage.put_bytes(key, payload)
    artifact = Artifact(artifact_type=artifact_type, storage_provider=stored["provider"], bucket=stored["bucket"], object_key=stored["object_key"], mime_type=mime_type, byte_size=stored["byte_size"], sha256=stored["sha256"], metadata_json={"immutable": True})
    db.add(artifact); db.flush(); return artifact


def publish_gold_release(db: Session, run_id: str, storage: StorageAdapter | None = None) -> GoldRelease:
    storage = storage or build_storage_adapter(get_settings())
    dataset = build_gold_dataset(db, run_id); json_payload = serialize_gold_json(dataset); digest = hashlib.sha256(json_payload).hexdigest()
    existing = db.query(GoldRelease).filter(GoldRelease.sha256 == digest).one_or_none()
    if existing is not None: return existing
    csv_payload = serialize_gold_csv(dataset)
    xlsx_payload = serialize_gold_xlsx(dataset)
    version = (db.query(func.max(GoldRelease.version)).filter(GoldRelease.processing_run_id == run_id).scalar() or 0) + 1
    prefix = f"gold/{run_id}/v{version:04d}/{digest}"
    json_artifact = _persist_artifact(db, storage, f"{prefix}.json", json_payload, "GOLD_JSON", "application/json")
    csv_artifact = _persist_artifact(db, storage, f"{prefix}.csv", csv_payload, "GOLD_CSV", "text/csv; charset=utf-8")
    xlsx_artifact = _persist_artifact(
        db,
        storage,
        f"{prefix}.xlsx",
        xlsx_payload,
        "GOLD_XLSX",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    release = GoldRelease(processing_run_id=run_id, version=version, schema_version=dataset["schema_version"], record_count=dataset["record_count"], sha256=digest, json_artifact_id=json_artifact.id, csv_artifact_id=csv_artifact.id, xlsx_artifact_id=xlsx_artifact.id)
    db.add(release); db.commit(); db.refresh(release); return release
