"""Settling a disputed line by its words.

The character vote disputes a line when the readers differ anywhere, often in
spacing, case or punctuation only. When two or more readers agree on the line's
words, and every one of those words is a common word of the language (or a
number), their reading is taken: two independent readers rarely make the same
mistake and land on a real word. Measured on the hand-checked pages of a grammar
book, about a third of the disputed lines settle this way and 97% of them are
right; without the word list it is 85%, too low to take on its own.

The word list comes from ECDICT (``word`` column), kept to words with a BNC or
corpus frequency, without forms OCR often produces by mistake ("lt" for "It").
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from app.evaluation.metrics import words

WORD_MAJORITY = "WORD_MAJORITY"
# Frequent words that are mostly misreadings in OCR output.
_CONFUSABLE = {"lt", "ln", "ls", "lf", "rn", "tbe"}
_CONTRACTIONS = {
    "i'm", "i've", "i'll", "i'd", "you're", "you've", "you'll", "you'd", "he's", "he'll", "he'd",
    "she's", "she'll", "she'd", "it's", "it'll", "we're", "we've", "we'll", "we'd", "they're",
    "they've", "they'll", "they'd", "that's", "there's", "what's", "who's", "where's", "let's",
    "don't", "doesn't", "didn't", "can't", "couldn't", "won't", "wouldn't", "shouldn't", "isn't",
    "aren't", "wasn't", "weren't", "haven't", "hasn't", "hadn't", "mustn't", "needn't",
}  # fmt: skip


@lru_cache(maxsize=4)
def load_lexicon(path: str) -> frozenset[str]:
    """Common English words from an ECDICT CSV."""
    found = set(_CONTRACTIONS) | {"a", "i"}
    with Path(path).open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            word = (row.get("word") or "").strip().lower()
            if re.fullmatch(r"[a-z]+(?:'[a-z]+)?", word) and any((row.get(k) or "0") not in ("", "0") for k in ("bnc", "frq")):
                found.add(word)
    return frozenset(found - _CONFUSABLE)


def settle_by_words(readings: dict[str, str], order: list[str], lexicon: frozenset[str]) -> tuple[str, list[str]] | None:
    """The reading two or more readers agree on word for word, if all its words are common; else None.

    ``readings`` maps reader name to text; ``order`` is the readers' priority, the
    first agreeing reader's text (with its punctuation) is the one kept.
    """
    groups: dict[tuple[str, ...], list[str]] = {}
    for name in order:
        text = readings.get(name)
        if text and words(text):
            groups.setdefault(tuple(words(text)), []).append(name)
    agreed = [(key, names) for key, names in groups.items() if len(names) >= 2]
    if len(agreed) != 1:
        return None
    key, names = agreed[0]
    if not all(word in lexicon or word.isdigit() for word in key):
        return None
    return readings[names[0]], names


def settle_parked_lines(db, run_id: str, lexicon: frozenset[str], *, dry_run: bool = False) -> dict:
    """Settle by words the lines a run has parked for arbitration, before any paid model sees them.

    A settled line is recorded the way an arbiter's answer is (``machine_arbitration``
    with arbiter ``word-majority``), so the rest of the engine reads its text and
    rebuilds the entries cut from the old text.
    """
    from datetime import UTC, datetime

    from app.models import ProcessingStep, SourceBlock
    from app.services.arbitration import ARBITRATED, parked_lines

    tasks = parked_lines(db, run_id, every_line=True)
    settled = 0
    for task in tasks:
        block = db.get(SourceBlock, task.target_entity_id)
        consensus = (block.metadata_json or {}).get("consensus") or {}
        primary = consensus.get("primary_text") or block.raw_text or ""
        others = consensus.get("other_readings") or {}
        result = settle_by_words({"primary": primary, **others}, ["primary", *others], lexicon)
        if result is None:
            continue
        settled += 1
        if dry_run:
            continue
        text, readers = result
        record = {
            "arbiter": "word-majority",
            "answer": text,
            "decided_at": datetime.now(UTC).isoformat(),
            "status": "ACCEPTED",
            "agrees_with": readers[0],
            "agreed_readers": readers,
            "text": text,
        }
        block.metadata_json = {**(block.metadata_json or {}), "machine_arbitration": record}
        task.source_context = {**(task.source_context or {}), "machine_arbitration": record}
        task.status = ARBITRATED
    if settled and not dry_run:
        step = (
            db.query(ProcessingStep)
            .filter(ProcessingStep.processing_run_id == run_id, ProcessingStep.sequence_no == 20)
            .one_or_none()
        )
        if step is not None:
            step.metrics = {**(step.metrics or {}), "blocks_fingerprint": "stale"}
    db.commit()
    return {"run_id": run_id, "parked_lines": len(tasks), "settled": settled, "dry_run": dry_run}
