"""Character-level consensus between independent OCR readings of one line.

No single engine reads a scanned page faithfully: each has its own systematic
slips. Where independent readers agree the text is confirmed; where two agree
against one the majority reading is taken and recorded; where all differ the
line is marked disputed and nothing is chosen for it.

Pronunciations in brackets are excluded from voting. No OCR engine reads the
phonetic alphabet, so agreement there would only be shared error.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

UNANIMOUS = "UNANIMOUS"
MAJORITY = "MAJORITY"
DISPUTED = "DISPUTED"
SINGLE_READER = "SINGLE_READER"

_PUNCTUATION = str.maketrans(
    {
        "（": "(", "）": ")", "［": "[", "］": "]", "：": ":", "；": ";", "，": ",",
        "！": "!", "？": "?", "“": '"', "”": '"', "‘": "'", "’": "'", "．": ".",
        "—": "-", "–": "-", "⋯": "…", "·": ".",
    }
)  # fmt: skip
_ELLIPSIS = re.compile(r"\.{2,}|…+")
_IPA = re.compile(r"[\[［][^\]］一-鿿]{1,40}[\]］]")
_MIN_SIMILARITY = 0.6
_MASK = "\u0000"


@dataclass(slots=True)
class Consensus:
    text: str
    status: str
    readers: int
    corrections: list[dict] = field(default_factory=list)
    disputes: list[dict] = field(default_factory=list)


def _canonical(text: str) -> tuple[str, list[int]]:
    """Comparison form of ``text`` and, per character, its index in ``text``.

    Width, quote style and spacing are typography, not content, so they are
    folded away before readings are compared.
    """
    characters: list[str] = []
    origin: list[int] = []
    for index, character in enumerate(text):
        folded = unicodedata.normalize("NFKC", character).translate(_PUNCTUATION)
        for piece in folded:
            if piece.isspace():
                continue
            if piece == _MASK and characters and characters[-1] == _MASK:
                continue  # a masked pronunciation counts once, whatever its length
            characters.append(piece)
            origin.append(index)
    joined = "".join(characters)
    # Collapse every spelling of an ellipsis to one character.
    result: list[str] = []
    kept: list[int] = []
    position = 0
    for match in _ELLIPSIS.finditer(joined):
        result.extend(joined[position : match.start()])
        kept.extend(origin[position : match.start()])
        result.append("…")
        kept.append(origin[match.start()])
        position = match.end()
    result.extend(joined[position:])
    kept.extend(origin[position:])
    return "".join(result), kept


_RARE_MARKS = "→"


def _without_marks(text: str) -> str:
    return re.sub(r"[→一\->,]", "", text)


def _mask_ipa(text: str) -> str:
    return _IPA.sub(lambda match: "[" + _MASK * (len(match.group(0)) - 2) + "]", text)


def _project(opcodes: list[tuple], start: int, end: int, other: str) -> str:
    """The stretch of ``other`` aligned with ``base[start:end]``."""
    pieces: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if i2 < start or i1 > end or (i1 == i2 and not start <= i1 <= end):
            continue
        if tag == "equal":
            low, high = max(i1, start), min(i2, end)
            if low < high:
                pieces.append(other[j1 + (low - i1) : j1 + (high - i1)])
        elif i1 == i2:
            if start <= i1 <= end:
                pieces.append(other[j1:j2])
        elif i1 < end and i2 > start:
            pieces.append(other[j1:j2])
    return "".join(pieces)


def build_consensus(base: str, others: list[str]) -> Consensus:
    """Vote ``base`` against the other readings of the same line."""
    masked_base, origin = _canonical(_mask_ipa(base))
    voters: list[tuple[str, list[tuple]]] = []
    for other in others:
        masked_other, _ = _canonical(_mask_ipa(other))
        matcher = SequenceMatcher(None, masked_base, masked_other, autojunk=False)
        if not masked_other or matcher.ratio() < _MIN_SIMILARITY:
            continue  # not a reading of this line; the reader abstains
        if any(mark in masked_base for mark in _RARE_MARKS):
            # Several engines have no arrow and print a dash, the character 一,
            # or nothing for it. That is a shared limitation, not a reading, so
            # such a stretch is taken to say what the base says.
            pieces: list[str] = []
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                mine, theirs = masked_base[i1:i2], masked_other[j1:j2]
                same = tag != "equal" and _without_marks(mine) == _without_marks(theirs)
                pieces.append(mine if same and any(m in mine for m in _RARE_MARKS) else theirs)
            masked_other = "".join(pieces)
            matcher = SequenceMatcher(None, masked_base, masked_other, autojunk=False)
        voters.append((masked_other, matcher.get_opcodes()))
    if not voters:
        return Consensus(base, SINGLE_READER, 1)

    spans: list[list[int]] = []
    for _, opcodes in voters:
        for tag, i1, i2, _, _ in opcodes:
            if tag != "equal":
                spans.append([i1, i2])
    if not spans:
        return Consensus(base, UNANIMOUS, 1 + len(voters))
    spans.sort()
    merged: list[list[int]] = [spans[0]]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    corrections: list[dict] = []
    disputes: list[dict] = []
    replacements: list[tuple[int, int, str]] = []
    for start, end in merged:
        mine = masked_base[start:end]
        theirs = [_project(opcodes, start, end, other) for other, opcodes in voters]
        if _MASK in mine or any(_MASK in item for item in theirs):
            continue  # inside a pronunciation: not voted on
        agreeing = [item for item in theirs if item == mine]
        if agreeing:
            continue  # the base reading has a second vote
        if len(theirs) >= 2 and len(set(theirs)) == 1:
            corrections.append({"from": mine, "to": theirs[0]})
            replacements.append((start, end, theirs[0]))
        else:
            disputes.append({"base": mine, "others": theirs})

    text = base
    for start, end, value in sorted(replacements, reverse=True):
        if start == end:
            at = origin[start] if start < len(origin) else len(text)
            text = text[:at] + value + text[at:]
        else:
            text = text[: origin[start]] + value + text[origin[end - 1] + 1 :]
    # Every difference was settled by a second vote, for or against the base.
    status = DISPUTED if disputes else MAJORITY
    return Consensus(text, status, 1 + len(voters), corrections, disputes)
