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
# Taken from a dictionary without any confirmation from the printed page.
DICTIONARY_ONLY = "DICTIONARY_ONLY"
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


# Modern (Gimson) transcription -> the older symbol inventory the book prints,
# longest sequences first.
_MODERN = (
    ("əʊ", "әu"), ("eɪ", "ei"), ("ɔɪ", "ɒi"), ("ɪə", "iә"), ("eə", "єә"), ("ɛə", "єә"),
    ("ʊə", "uә"), ("ɜː", "ә:"), ("ɔː", "ɒ:"), ("ɑː", "ɑ:"), ("iː", "i:"), ("uː", "u:"),
    ("ɪ", "i"), ("ʊ", "u"), ("ɹ", "r"), ("ə", "ә"), ("ɛ", "e"), ("ɜ", "ә"), ("ɡ", "g"),
    ("ː", ":"), ("ɫ", "l"), ("ɐ", "ʌ"), ("ɔ", "ɒ"), ("a", "æ"),
)  # fmt: skip
_ONSETS = {
    "pr", "br", "tr", "dr", "kr", "gr", "fr", "θr", "ʃr", "pl", "bl", "kl", "gl", "fl",
    "sl", "sp", "st", "sk", "sm", "sn", "sw", "tw", "dw", "kw", "spr", "str", "skr",
    "spl", "skw", "tʃ", "dʒ",
}  # fmt: skip
_CONSONANTS = set("pbtdkgfvθðszʃʒhmnŋlrwj")
_NUCLEUS = re.compile(r"[aeiouәʌæɒɑє]+:?")


def modern_to_book_symbols(phonetic: str) -> str:
    """Rewrite a modern transcription with the book's symbols and stress placement."""
    text = phonetic.replace(" ", "").strip("/")
    text = text.replace("aɪ", "\x01").replace("aʊ", "\x02")
    for modern, book in _MODERN:
        text = text.replace(modern, book)
    text = text.replace("\x01", "ai").replace("\x02", "au")
    text = text.replace("ˈ", "'").replace("ˌ", ".")
    if len(_NUCLEUS.findall(text)) <= 1:
        return text.replace("'", "").replace(".", "")  # one syllable: no stress mark printed
    # These dictionaries put the mark before the vowel; the book puts it before the syllable.
    moved = ""
    for character in text:
        if character not in "'.":
            moved += character
            continue
        start = len(moved)
        while start > 0 and moved[start - 1] in _CONSONANTS:
            start -= 1
        cluster = moved[start:]
        keep = 0
        while keep < len(cluster):
            onset = cluster[keep:]
            if (
                len(onset) == 1
                or onset in _ONSETS
                or (onset[-1] == "j" and (len(onset) == 2 or onset[:-1] in _ONSETS))
            ):
                break
            keep += 1
        moved = moved[: start + keep] + character + cluster[keep:]
    return moved


def load_dictionaries(spec: str) -> list[tuple[str, dict[str, list[str]]]]:
    """Load ``format:path`` entries separated by commas, in priority order.

    Formats: ``ecdict`` (CSV with word/phonetic columns), ``britfone``
    (``WORD, p h o n e s``) and ``ipadict`` (``word<TAB>/ipa/, /ipa/``).
    """
    loaded: list[tuple[str, dict[str, list[str]]]] = []
    for item in filter(None, (part.strip() for part in spec.split(","))):
        kind, _, location = item.partition(":")
        path = Path(location)
        if not path.is_file():
            continue
        entries: dict[str, list[str]] = {}
        if kind == "ecdict":
            entries = {word: [form] for word, form in load_pronunciation_dictionary(path).items()}
            name = "ECDICT"
        elif kind == "britfone":
            name = "Britfone"
            for line in path.read_text(encoding="utf-8").splitlines():
                word, _, phones = line.partition(",")
                if phones.strip():
                    key = re.sub(r"\(\d+\)$", "", word.strip()).lower()
                    entries.setdefault(key, []).append(modern_to_book_symbols(phones))
        elif kind == "ipadict":
            name = "ipa-dict"
            for line in path.read_text(encoding="utf-8").splitlines():
                word, _, forms = line.partition("\t")
                for form in forms.split(","):
                    if form.strip():
                        entries.setdefault(word.lower(), []).append(
                            modern_to_book_symbols(form.strip())
                        )
        else:
            raise ValueError(f"unsupported pronunciation dictionary format: {kind}")
        loaded.append((name, entries))
    return loaded


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
    dictionaries: list[tuple[str, dict[str, list[str]]]],
    *,
    fill_from_dictionary: bool = True,
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
        # Several pronunciations on one line: no single form can be checked against them.
        several = any(len(found) > 1 for found in brackets.values())
        readings = (
            {} if several else {n: found[0].strip() for n, found in brackets.items() if found}
        )
        forms = [
            (name, form)
            for name, entries in dictionaries
            for form in entries.get(entry.lemma.lower(), [])
        ]
        usable.append((entry, block, unverified, readings, forms, several))

    model = ConfusionModel(min_count=min_count, min_share=min_share)
    # The first dictionary is written in the book's own style and teaches the readers' habits.
    model.learn([(forms[0][1], readings) for *_, readings, forms, _ in usable if forms and readings])

    for entry, block, unverified, readings, forms, several in usable:
        if (
            db.query(Pronunciation).filter(Pronunciation.vocabulary_entry_id == entry.id).first()
            is not None
        ):
            outcomes["ALREADY_HAS_PRONUNCIATION"] += 1
            continue
        if not forms:
            outcomes["NO_DICTIONARY_ENTRY"] += 1
            continue
        chosen = None
        for name, form in forms:
            outcome, stress_seen = corroborate(form, readings, model)
            if outcome == "CORROBORATED":
                chosen = (name, form, CORROBORATED, stress_seen, outcome)
                break
        if chosen is None:
            if not fill_from_dictionary:
                outcomes["NOT_CORROBORATED"] += 1
                continue
            # Whatever the page prints could not be confirmed: the first
            # dictionary's form is supplied and labelled as such.
            reason = "MULTIPLE_PRONUNCIATIONS" if several else corroborate(*forms[0][1:], readings, model)[0]
            chosen = (forms[0][0], forms[0][1], DICTIONARY_ONLY, False, reason)
        name, form, status, stress_seen, reason = chosen
        outcomes[status] += 1
        pronunciation = Pronunciation(
            vocabulary_entry_id=entry.id,
            pronunciation_order=1,
            ipa=to_book_notation(form),
            verification_status=status,
        )
        db.add(pronunciation)
        db.flush()
        db.add(
            ProvenanceRecord(
                processing_run_id=run_id,
                target_entity_type="Pronunciation",
                target_entity_id=pronunciation.id,
                target_field_path="ipa",
                provenance_type=(
                    "SOURCE_CORROBORATED" if status == CORROBORATED else "ENRICHMENT_DICTIONARY"
                ),
                source_entry_id=entry.source_entry_id,
                source_block_id=block.id,
                page_id=block.page_id,
                source_text=unverified.text,
                metadata_json={
                    "method": "ipa-dictionary-corroboration@1.1.0",
                    "dictionary": name,
                    "dictionary_phonetic": form,
                    "dictionary_forms": [list(item) for item in forms],
                    "ocr_readings": readings,
                    "stress_position_seen": stress_seen,
                    "reason": reason,
                },
            )
        )
    db.commit()
    return {
        "run_id": run_id,
        "ocr_pronunciations": len(candidates),
        "corroborated": outcomes[CORROBORATED],
        "dictionary_only": outcomes[DICTIONARY_ONLY],
        "outcomes": dict(sorted(outcomes.items())),
    }


def corroborate_run_from_settings(db: Session, run_id: str) -> dict:
    """Pipeline entry point: does nothing unless a dictionary is configured."""
    from app.settings import get_settings

    dictionaries = load_dictionaries(get_settings().pronunciation_dictionaries)
    if not dictionaries:
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
    return corroborate_run(db, run_id, dictionaries)
