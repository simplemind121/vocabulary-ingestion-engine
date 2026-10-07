from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.adapters.pdf_native import PyMuPDFNativeAdapter
from app.models import (
    Definition,
    Pronunciation,
    ProvenanceRecord,
    ReviewTask,
    Sense,
    SourceBlock,
    SourceEntry,
    SourceEntryBlock,
    VocabularyEntry,
    VocabularyField,
)
from app.services.book_structure import bare_headword, is_entry_head
from app.services.field_parser import parse_source_entry as parse_real_book_entry

_POS_TOKEN = r"(?:n|v|vt|vi|adj|adv|prep|conj|pron|det|excl)\."
_ENTRY = re.compile(
    r"^(?P<lemma>[A-Za-z][A-Za-z'’-]{1,63})"
    r"(?:\s+/(?P<ipa>[^/]+)/)?"
    rf"(?:\s+(?P<pos>{_POS_TOKEN}(?:/{_POS_TOKEN})*))?"
    r"(?:\s+(?P<definition>.+))?$"
)


@dataclass(slots=True)
class ParsedEntry:
    lemma: str
    ipa: str | None
    part_of_speech: str | None
    definition: str | None
    source_fields: dict[str, list[str]]
    # Second and later pronunciations/senses printed for the same headword.
    extra_pronunciations: list[str] = field(default_factory=list)
    extra_senses: list[dict] = field(default_factory=list)


def parse_source_entry_text(text: str) -> ParsedEntry:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and (
        is_entry_head(lines[0])
        or ("[" in lines[0] and "]" in lines[0])
        or (len(lines) > 1 and bare_headword(lines[0]) is not None)
    ):
        real = parse_real_book_entry(lines)
        first_sense = real.senses[0] if real.senses else {}
        return ParsedEntry(
            lemma=real.lemma,
            ipa=real.ipa,
            part_of_speech=first_sense.get("pos"),
            definition=first_sense.get("definition"),
            source_fields={
                "MEMORY_NOTE": real.memory_notes,
                "COLLOCATION": real.collocations,
                "EXAMPLE": real.examples,
                "DERIVATIVE": real.derivatives,
                "SYNONYM": real.synonyms,
                "ANTONYM": real.antonyms,
                "EXAM_NOTE": real.exam_notes,
                "EXAM_QUESTION": real.exam_questions,
                "EXAM_EXPLANATION": real.exam_explanations,
            },
            extra_pronunciations=real.pronunciations[1:],
            extra_senses=real.senses[1:],
        )

    normalized = " ".join(text.split())
    match = _ENTRY.match(normalized)
    if match is None:
        raise ValueError("source entry does not match supported structured formats")
    definition = match.group("definition")
    return ParsedEntry(
        lemma=match.group("lemma"),
        ipa=match.group("ipa"),
        part_of_speech=match.group("pos"),
        definition=definition.strip() if definition else None,
        source_fields={},
    )


def _demote_unverified_ocr_ipa(parsed: ParsedEntry, block: SourceBlock | None) -> None:
    """Keep IPA read by OCR as source text, not as a verified pronunciation.

    OCR engines have no phonetic alphabet: stress marks vanish and symbols
    become look-alike letters. Unless a human confirmed the line, the reading
    is preserved under IPA_OCR_UNVERIFIED for a later stage to resolve.
    """
    if block is None or block.source_engine == PyMuPDFNativeAdapter.name:
        return
    review = (block.metadata_json or {}).get("human_ocr_review") or {}
    if review.get("decision") == "ACCEPT":
        return
    readings = [item for item in [parsed.ipa, *parsed.extra_pronunciations] if item]
    if readings:
        parsed.source_fields = {**parsed.source_fields, "IPA_OCR_UNVERIFIED": readings}
    parsed.ipa = None
    parsed.extra_pronunciations = []


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
            try:
                parsed = parse_source_entry_text(source_entry.raw_text)
            except ValueError:
                extracted += 1
                continue
            link = (
                db.query(SourceEntryBlock)
                .filter(SourceEntryBlock.source_entry_id == source_entry.id)
                .order_by(SourceEntryBlock.block_order)
                .first()
            )
            block = db.get(SourceBlock, link.source_block_id) if link else None
            _demote_unverified_ocr_ipa(parsed, block)
            _persist_source_fields(
                db,
                run_id=run_id,
                vocab=vocab,
                parsed=parsed,
                source_entry=source_entry,
                block=block,
            )
            extracted += 1
            continue

        try:
            parsed = parse_source_entry_text(source_entry.raw_text)
        except ValueError as exc:
            vocab.verification_status = "REVIEW_REQUIRED"
            existing_review = (
                db.query(ReviewTask)
                .filter(
                    ReviewTask.processing_run_id == run_id,
                    ReviewTask.target_entity_type == "VocabularyEntry",
                    ReviewTask.target_entity_id == vocab.id,
                    ReviewTask.reason_code == "STRUCTURED_EXTRACTION_UNCERTAIN",
                    ReviewTask.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"]),
                )
                .first()
            )
            if existing_review is None:
                db.add(
                    ReviewTask(
                        processing_run_id=run_id,
                        reason_code="STRUCTURED_EXTRACTION_UNCERTAIN",
                        status="OPEN",
                        target_entity_type="VocabularyEntry",
                        target_entity_id=vocab.id,
                        target_field_path=None,
                        source_context={
                            "source_entry_id": source_entry.id,
                            "raw_text": source_entry.raw_text,
                            "error": str(exc),
                        },
                        candidate_values=[],
                    )
                )
            review_required += 1
            continue

        link = (
            db.query(SourceEntryBlock)
            .filter(SourceEntryBlock.source_entry_id == source_entry.id)
            .order_by(SourceEntryBlock.block_order)
            .first()
        )
        block = db.get(SourceBlock, link.source_block_id) if link else None
        _demote_unverified_ocr_ipa(parsed, block)

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
                language="zh",
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

        for order, ipa in enumerate(parsed.extra_pronunciations, start=2):
            extra = Pronunciation(
                vocabulary_entry_id=vocab.id,
                pronunciation_order=order,
                ipa=ipa,
                verification_status="PARSED",
            )
            db.add(extra)
            db.flush()
            _add_provenance(
                db,
                run_id=run_id,
                entity_type="Pronunciation",
                entity_id=extra.id,
                field_path="ipa",
                source_entry=source_entry,
                block=block,
                source_text=ipa,
            )
        for order, item in enumerate(parsed.extra_senses, start=2):
            extra_sense = Sense(
                vocabulary_entry_id=vocab.id,
                sense_order=order,
                part_of_speech=item.get("pos"),
                verification_status="PARSED",
            )
            db.add(extra_sense)
            db.flush()
            if item.get("pos"):
                _add_provenance(
                    db,
                    run_id=run_id,
                    entity_type="Sense",
                    entity_id=extra_sense.id,
                    field_path="part_of_speech",
                    source_entry=source_entry,
                    block=block,
                    source_text=item["pos"],
                )
            if item.get("definition"):
                extra_definition = Definition(
                    sense_id=extra_sense.id,
                    definition_order=1,
                    text=item["definition"],
                    language="zh",
                    verification_status="PARSED",
                )
                db.add(extra_definition)
                db.flush()
                _add_provenance(
                    db,
                    run_id=run_id,
                    entity_type="Definition",
                    entity_id=extra_definition.id,
                    field_path="text",
                    source_entry=source_entry,
                    block=block,
                    source_text=item["definition"],
                )

        _persist_source_fields(
            db,
            run_id=run_id,
            vocab=vocab,
            parsed=parsed,
            source_entry=source_entry,
            block=block,
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
            metadata_json={"method": "structured-extractor@0.2.0"},
        )
    )



def _persist_source_fields(
    db: Session,
    *,
    run_id: str,
    vocab: VocabularyEntry,
    parsed: ParsedEntry,
    source_entry: SourceEntry,
    block: SourceBlock | None,
) -> None:
    for field_type, values in parsed.source_fields.items():
        for field_order, value in enumerate(values, start=1):
            text = value.strip()
            if not text:
                continue
            existing = (
                db.query(VocabularyField)
                .filter(
                    VocabularyField.vocabulary_entry_id == vocab.id,
                    VocabularyField.field_type == field_type,
                    VocabularyField.field_order == field_order,
                )
                .one_or_none()
            )
            if existing is not None:
                continue
            field = VocabularyField(
                vocabulary_entry_id=vocab.id,
                field_type=field_type,
                field_order=field_order,
                text=text,
                language=_field_language(field_type),
                verification_status="PARSED",
            )
            db.add(field)
            db.flush()
            _add_provenance(
                db,
                run_id=run_id,
                entity_type="VocabularyField",
                entity_id=field.id,
                field_path="text",
                source_entry=source_entry,
                block=block,
                source_text=text,
            )


def _field_language(field_type: str) -> str | None:
    if field_type in {"MEMORY_NOTE", "EXAM_EXPLANATION"}:
        return "zh"
    return None
