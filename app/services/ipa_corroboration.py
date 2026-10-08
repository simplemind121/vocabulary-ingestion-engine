"""Recover printed pronunciations that OCR cannot read, without guessing.

OCR engines have no phonetic alphabet: they drop stress marks and print a
look-alike letter for every special symbol. But they do so consistently, and a
pronouncing dictionary knows the candidate transcription of the headword. If
every reader's garbled reading is exactly what that reader usually prints for
the dictionary's transcription, the transcription is taken to be what the book
prints. If any reader contradicts it, nothing is filled in.

A pronunciation recovered this way is not a direct source reading and is
labelled DICTIONARY_CORROBORATED, with the dictionary form and every OCR
reading kept as provenance.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import (
    Pronunciation,
    ProvenanceRecord,
    SourceBlock,
    SourceEntryBlock,
    VocabularyEntry,
    VocabularyField,
)

CORROBORATED = "DICTIONARY_CORROBORATED"
UNVERIFIED_FIELD = "IPA_OCR_UNVERIFIED"
_BRACKET = re.compile(r"[\[［]([^\]］一-鿿]{1,40})[\]］]")
_STRESS = "'ˈˌ.,`’‘|/"
# The dictionary writes in an ASCII-friendly variant of the same transcription
# the book prints; this is the symbol-for-symbol correspondence.
_BOOK_NOTATION = str.maketrans({"ә": "ə", "ɒ": "ɔ", ":": "ː", "'": "ˈ", ".": "ˌ"})


def to_book_notation(phonetic: str) -> str:
    return phonetic.translate(_BOOK_NOTATION)


def load_pronunciation_dictionary(path: str | Path) -> dict[str, str]:
    """Read an ECDICT-format CSV (columns ``word`` and ``phonetic``)."""
    csv.field_size_limit(1 << 30)
    entries: dict[str, str] = {}
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("phonetic"):
                entries.setdefault(row["word"].lower(), row["phonetic"])
    return entries


def _clean(text: str) -> str:
    return re.sub(r"\s", "", text).replace("：", ":").replace("ː", ":")


def _symbols(text: str) -> str:
    return "".join(character for character in _clean(text) if character not in _STRESS)


@dataclass(slots=True)
class ConfusionModel:
    """What each reader usually prints for each phonetic symbol, learned from the book."""

    min_count: int = 10
    min_share: float = 0.03
    _pairs: dict[str, Counter] = field(default_factory=dict)
    _totals: dict[str, Counter] = field(default_factory=dict)

    def learn(self, samples: list[tuple[str, dict[str, str]]]) -> None:
        for phonetic, readings in samples:
            symbols = _symbols(phonetic)
            for reader, reading in readings.items():
                self._totals.setdefault(reader, Counter()).update(symbols)
                pairs = self._pairs.setdefault(reader, Counter())
                matcher = SequenceMatcher(None, symbols, _symbols(reading), autojunk=False)
                for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                    if tag == "equal":
                        continue
                    mine, theirs = symbols[i1:i2], _symbols(reading)[j1:j2]
                    if len(mine) == len(theirs):
                        pairs.update(zip(mine, theirs, strict=True))
                    elif len(mine) == 1:
                        pairs[(mine, theirs)] += 1
                    elif not theirs:
                        pairs.update((symbol, "") for symbol in mine)

    def allowed(self, reader: str, symbol: str, printed: str) -> bool:
        count = self._pairs.get(reader, Counter())[(symbol, printed)]
        total = self._totals.get(reader, Counter())[symbol]
        return count >= self.min_count and total > 0 and count / total >= self.min_share

    def consistent(self, reader: str, phonetic: str, reading: str) -> bool:
        """Is ``reading`` what this reader would print for ``phonetic``?"""
        symbols, printed = _symbols(phonetic), _symbols(reading)
        reachable = {0}
        for symbol in symbols:
            following: set[int] = set()
            for position in reachable:
                if position < len(printed) and printed[position] == symbol:
                    following.add(position + 1)
                if self.allowed(reader, symbol, ""):
                    following.add(position)
                for width in (1, 2):
                    chunk = printed[position : position + width]
                    if len(chunk) == width and self.allowed(reader, symbol, chunk):
                        following.add(position + width)
            reachable = following
            if not reachable:
                return False
        return len(printed) in reachable

    def stress_agrees(self, reader: str, phonetic: str, reading: str) -> bool | None:
        """Compare the primary stress position where the reader printed one."""
        cleaned = _clean(reading)
        mark = re.search(r"['ˈ]", cleaned)
        if mark is None or "'" not in phonetic:
            return None
        return self.consistent(reader, phonetic.split("'")[0], cleaned[: mark.start()])


def corroborate(
    phonetic: str | None, readings: dict[str, str], model: ConfusionModel
) -> tuple[str, bool]:
    """Return (outcome, stress_seen) for one headword."""
    if not phonetic:
        return "NO_DICTIONARY_ENTRY", False
    if len(readings) < 2:
        return "FEWER_THAN_TWO_READINGS", False
    if not all(model.consistent(name, phonetic, text) for name, text in readings.items()):
        return "READINGS_CONTRADICT_DICTIONARY", False
    stress = [
        verdict
        for name, text in readings.items()
        if (verdict := model.stress_agrees(name, phonetic, text)) is not None
    ]
    if stress and not all(stress):
        return "STRESS_POSITION_DIFFERS", True
    return "CORROBORATED", bool(stress) or "'" not in phonetic


def corroborate_run(
    db: Session,
    run_id: str,
    dictionary: dict[str, str],
    *,
    dictionary_name: str = "ECDICT",
    min_count: int = 10,
    min_share: float = 0.03,
) -> dict:
    """Fill in pronunciations for OCR entries where dictionary and readers agree."""
    candidates = []
    for entry, unverified in (
        db.query(VocabularyEntry, VocabularyField)
        .join(VocabularyField, VocabularyField.vocabulary_entry_id == VocabularyEntry.id)
        .filter(
            VocabularyEntry.processing_run_id == run_id,
            VocabularyField.field_type == UNVERIFIED_FIELD,
            VocabularyField.field_order == 1,
        )
        .all()
    ):
        link = (
            db.query(SourceEntryBlock)
            .filter(SourceEntryBlock.source_entry_id == entry.source_entry_id)
            .order_by(SourceEntryBlock.block_order)
            .first()
        )
        block = db.get(SourceBlock, link.source_block_id) if link else None
        if block is None:
            continue
        consensus = (block.metadata_json or {}).get("consensus") or {}
        texts = {
            "primary": consensus.get("primary_text") or block.raw_text or "",
            **(consensus.get("other_readings") or {}),
        }
        brackets = {name: _BRACKET.findall(text) for name, text in texts.items()}
        candidates.append((entry, block, unverified, brackets))

    outcomes: Counter = Counter()
    usable = []
    for entry, block, unverified, brackets in candidates:
        if any(len(found) > 1 for found in brackets.values()):
            # Several pronunciations on one line: one dictionary form cannot vouch for them.
            outcomes["MULTIPLE_PRONUNCIATIONS"] += 1
            continue
        readings = {name: found[0].strip() for name, found in brackets.items() if found}
        usable.append((entry, block, unverified, readings, dictionary.get(entry.lemma.lower())))

    model = ConfusionModel(min_count=min_count, min_share=min_share)
    model.learn([(phonetic, readings) for *_, readings, phonetic in usable if phonetic])

    for entry, block, unverified, readings, phonetic in usable:
        if (
            db.query(Pronunciation).filter(Pronunciation.vocabulary_entry_id == entry.id).first()
            is not None
        ):
            outcomes["ALREADY_HAS_PRONUNCIATION"] += 1
            continue
        outcome, stress_seen = corroborate(phonetic, readings, model)
        outcomes[outcome] += 1
        if outcome != "CORROBORATED":
            continue
        pronunciation = Pronunciation(
            vocabulary_entry_id=entry.id,
            pronunciation_order=1,
            ipa=to_book_notation(phonetic),
            verification_status=CORROBORATED,
        )
        db.add(pronunciation)
        db.flush()
        db.add(
            ProvenanceRecord(
                processing_run_id=run_id,
                target_entity_type="Pronunciation",
                target_entity_id=pronunciation.id,
                target_field_path="ipa",
                provenance_type="SOURCE_CORROBORATED",
                source_entry_id=entry.source_entry_id,
                source_block_id=block.id,
                page_id=block.page_id,
                source_text=unverified.text,
                metadata_json={
                    "method": "ipa-dictionary-corroboration@1.0.0",
                    "dictionary": dictionary_name,
                    "dictionary_phonetic": phonetic,
                    "ocr_readings": readings,
                    "stress_position_seen": stress_seen,
                },
            )
        )
    db.commit()
    return {
        "run_id": run_id,
        "ocr_pronunciations": len(candidates),
        "corroborated": outcomes["CORROBORATED"],
        "outcomes": dict(sorted(outcomes.items())),
    }


def corroborate_run_from_settings(db: Session, run_id: str) -> dict:
    """Pipeline entry point: does nothing unless a dictionary is configured."""
    from app.settings import get_settings

    path = get_settings().pronunciation_dictionary
    if path is None or not Path(path).is_file():
        return {"run_id": run_id, "skipped": "no pronunciation dictionary configured"}
    pending = (
        db.query(VocabularyField)
        .join(VocabularyEntry, VocabularyEntry.id == VocabularyField.vocabulary_entry_id)
        .filter(
            VocabularyEntry.processing_run_id == run_id,
            VocabularyField.field_type == UNVERIFIED_FIELD,
        )
        .first()
    )
    if pending is None:
        return {"run_id": run_id, "skipped": "no OCR pronunciations to corroborate"}
    return corroborate_run(db, run_id, load_pronunciation_dictionary(path))
