"""Standard text metrics: edit distance, character and word error rates, word precision and recall."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def normalize(text: str) -> str:
    """Compatibility forms folded, curly quotes and dashes made plain, whitespace collapsed."""
    return " ".join(unicodedata.normalize("NFKC", text).translate(_QUOTES).split())


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", normalize(text).lower())


def levenshtein(a: Sequence, b: Sequence) -> int:
    """Edit distance between two sequences (characters or tokens), bit-parallel (Hyyrö 2001)."""
    if len(a) < len(b):
        a, b = b, a
    m = len(b)
    if m == 0:
        return len(a)
    peq: dict = {}
    for i, item in enumerate(b):
        peq[item] = peq.get(item, 0) | (1 << i)
    mask = (1 << m) - 1
    top = 1 << (m - 1)
    pv, mv, score = mask, 0, m
    for item in a:
        eq = peq.get(item, 0)
        xv = eq | mv
        xh = (((eq & pv) + pv) ^ pv) | eq
        ph = mv | (~(xh | pv) & mask)
        mh = pv & xh
        if ph & top:
            score += 1
        elif mh & top:
            score -= 1
        ph = ((ph << 1) | 1) & mask
        mh = (mh << 1) & mask
        pv = mh | (~(xv | ph) & mask)
        mv = ph & xv
    return score


def cer(hypothesis: str, reference: str) -> float:
    """Character error rate: edits needed per reference character."""
    hypothesis, reference = normalize(hypothesis), normalize(reference)
    return levenshtein(hypothesis, reference) / max(len(reference), 1)


def wer(hypothesis: str, reference: str) -> float:
    reference_words = words(reference)
    return levenshtein(words(hypothesis), reference_words) / max(len(reference_words), 1)


def ned(hypothesis: str, reference: str) -> float:
    """Normalized edit distance (0 identical, 1 nothing in common), as document-parsing benchmarks report it."""
    hypothesis, reference = normalize(hypothesis), normalize(reference)
    return levenshtein(hypothesis, reference) / max(len(hypothesis), len(reference), 1)


def word_scores(hypothesis: str, reference: str) -> dict:
    """Order-free word precision, recall and F1 (multisets): reading order does not count."""
    found, wanted = Counter(words(hypothesis)), Counter(words(reference))
    hit = sum((found & wanted).values())
    precision = hit / max(sum(found.values()), 1)
    recall = hit / max(sum(wanted.values()), 1)
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "hit": hit,
        "found": sum(found.values()),
        "wanted": sum(wanted.values()),
    }
