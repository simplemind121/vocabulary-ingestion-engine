from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import (
    Definition,
    Pronunciation,
    ProvenanceRecord,
    Sense,
    SourceBlock,
    SourceEntry,
    SourceEntryBlock,
    VocabularyEntry,
)

_ENTRY = re.compile(
    r"^(?P<lemma>[A-Za-z][A-Za-z'’-]{1,63})"
    r"(?:\s+/(?P<ipa>[^/]+)/)?"
    r"(?:\s+(?P<pos>n\.|v\.|adj\.|adv\.|prep\.|conj\.|pron\.|det\.|excl\.))?"
    r"(?:\s+(?P<definition>.+))?$"
)


@dataclass(slots=True)
class ParsedEntry:
    lemma: str
    ipa: str | None
    part_of_speech: str | None
    definition: str | None


def parse_source_entry_text(text: str) -> ParsedEntry:
    normalized = " ".join(text.split())
    match = _ENTRY.match(normalized)
    if match is None:
        raise ValueError("source entry does not match baseline structured format")
    definition = match.group("definition")
    return ParsedEntry(
        lemma=match.group("lemma"),
        ipa=match.group("ipa"),
        part_of_speech=match.group("pos"),
        definition=definition.strip() if definition else None,
    )


def extract_canonical_fields(db: Session, run_id: str) -> dict:
    source_entries = (
        db.query(SourceEntry)
        .filter(SourceEntry.processing_run_id == run_id)
        .order_by(SourceEntry.entry_order)
        .all()
    )
    extracted = 0
    review_required = 0

    for source_entry in source_entries:
        vocab = (
            db.query(VocabularyEntry)
            .filter(VocabularyEntry.source_entry_id == source_entry.id)
            .one_or_none()
        )
        if vocab is None:
            continue

        existing_sense = (
            db.query(Sense)
            .filter(Sense.vocabulary_entry_id == vocab.id)
            .first()
        )
        if existing_sense is not None:
            extracted += 1
            continue

        try:
            parsed = parse_source_entry_text(source_entry.raw_text)
        except ValueError:
            vocab.verification_status = "REVIEW_REQUIRED"
            review_required += 1
            continue

        link = (
            db.query(SourceEntryBlock)
            .filter(SourceEntryBlock.source_entry_id == source_entry.id)
            .order_by(SourceEntryBlock.block_order)
            .first()
        )
        block = db.get(SourceBlock, link.source_block_id) if link else None

        vocab.lemma = parsed.lemma
        _add_provenance(
            db,
            run_id=run_id,
            entity_type="VocabularyEntry",
            entity_id=vocab.id,
            field_path="lemma",
            source_entry=source_entry,
            block=block,
            source_text=parsed.lemma,
        )

        if parsed.ipa:
            pronunciation = Pronunciation(
                vocabulary_entry_id=vocab.id,
                pronunciation_order=1,
                ipa=parsed.ipa,
                verification_status="PARSED",
            )
            db.add(pronunciation)
            db.flush()
            _add_provenance(
                db,
                run_id=run_id,
                entity_type="Pronunciation",
                entity_id=pronunciation.id,
                field_path="ipa",
                source_entry=source_entry,
                block=block,
                source_text=parsed.ipa,
            )

        sense = Sense(
            vocabulary_entry_id=vocab.id,
            sense_order=1,
            part_of_speech=parsed.part_of_speech,
            verification_status="PARSED",
        )
        db.add(sense)
        db.flush()

        if parsed.part_of_speech:
            _add_provenance(
                db,
                run_id=run_id,
                entity_type="Sense",
                entity_id=sense.id,
                field_path="part_of_speech",
                source_entry=source_entry,
                block=block,
                source_text=parsed.part_of_speech,
            )

        if parsed.definition:
            definition = Definition(
                sense_id=sense.id,
                definition_order=1,
                text=parsed.definition,
                language="en",
                verification_status="PARSED",
            )
            db.add(definition)
            db.flush()
            _add_provenance(
                db,
                run_id=run_id,
                entity_type="Definition",
                entity_id=definition.id,
                field_path="text",
                source_entry=source_entry,
                block=block,
                source_text=parsed.definition,
            )

        extracted += 1

    db.commit()
    return {
        "run_id": run_id,
        "extracted_entries": extracted,
        "review_required": review_required,
    }


def _add_provenance(
    db: Session,
    *,
    run_id: str,
    entity_type: str,
    entity_id: str,
    field_path: str,
    source_entry: SourceEntry,
    block: SourceBlock | None,
    source_text: str,
) -> None:
    db.add(
        ProvenanceRecord(
            processing_run_id=run_id,
            target_entity_type=entity_type,
            target_entity_id=entity_id,
            target_field_path=field_path,
            provenance_type="SOURCE_DIRECT",
            source_entry_id=source_entry.id,
            source_block_id=block.id if block else None,
            page_id=block.page_id if block else None,
            source_text=source_text,
            metadata_json={"method": "baseline-structured-extractor@0.1.0"},
        )
    )
