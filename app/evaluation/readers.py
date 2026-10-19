"""How well each reader reads a book, measured page by page against Gold pages.

A reader's text for a page is its readings of the page's lines in reading order.
Readers that read whole bands of the page give the same band to neighbouring
lines (both columns of a two-column page, for one); a repeat of the previous
line's reading is counted once.

CER is reported twice: in the reader's own line order, and with its lines put
in the Gold page's order (each line placed where its word pairs occur on the
Gold page). The difference is what reading order costs; the second figure is
the reading itself.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import pairwise

from app.evaluation.gold import DEV, TEST, page_text, split_of
from app.evaluation.metrics import cer, levenshtein, normalize, word_scores, words

VOTED = "voted"


def reader_lines(lines: list[dict]) -> dict[str, list[str]]:
    texts: dict[str, list[str]] = defaultdict(list)
    for line in lines:
        texts[VOTED].append(line["text"])
        if line.get("primary"):
            texts["primary"].append(line["primary"])
        for name, reading in (line.get("readings") or {}).items():
            if reading and (not texts[name] or texts[name][-1] != reading):
                texts[name].append(reading)
    return dict(texts)


def gold_order(parts: list[str], reference: str) -> list[str]:
    """The lines sorted by where they start in the reference; lines found nowhere go to the end.

    Each pair of neighbouring words in a line votes for the line's start at every
    place the same pair occurs in the reference; the most voted start wins.
    """
    ref = words(reference)
    where: dict[tuple, list[int]] = defaultdict(list)
    for i in range(len(ref) - 1):
        where[(ref[i], ref[i + 1])].append(i)
    placed = []
    for order, part in enumerate(parts):
        mine = words(part)
        votes: Counter = Counter()
        for offset, pair in enumerate(pairwise(mine)):
            votes.update(i - offset for i in where.get(pair, []))
        start = votes.most_common(1)[0][0] if votes else len(ref) + order
        placed.append((start, order, part))
    return [part for _, _, part in sorted(placed)]


def evaluate(lines_by_page: dict[int, list[dict]], gold: dict[int, dict]) -> dict:
    """Per reader and split: word precision/recall/F1 (order-free), CER and WER (in reading order)."""
    totals: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(float))
    pages: dict[str, list] = defaultdict(list)
    for number, tree in sorted(gold.items()):
        reference = page_text(tree)
        if not reference:
            continue
        split = split_of(tree)
        for name, parts in reader_lines(lines_by_page.get(number, [])).items():
            hypothesis = " ".join(parts)
            ordered = " ".join(gold_order(parts, reference))
            scores = word_scores(hypothesis, reference)
            total = totals[(name, split)]
            for key in ("hit", "found", "wanted"):
                total[key] += scores[key]
            total["char_edits"] += levenshtein(normalize(hypothesis), normalize(reference))
            total["ordered_char_edits"] += levenshtein(normalize(ordered), normalize(reference))
            total["chars"] += len(normalize(reference))
            total["word_edits"] += levenshtein(words(hypothesis), words(reference))
            total["pages"] += 1
            pages[name].append({"page": number, "split": split, "kind": tree.get("kind") or "other", "recall": round(scores["recall"], 4),
                                "precision": round(scores["precision"], 4), "cer": round(cer(hypothesis, reference), 4),
                                "cer_in_gold_order": round(cer(ordered, reference), 4)})
    report: dict = {}
    for (name, split), t in sorted(totals.items()):
        precision = t["hit"] / max(t["found"], 1)
        recall = t["hit"] / max(t["wanted"], 1)
        report.setdefault(name, {})[split] = {
            "pages": int(t["pages"]),
            "word_precision": round(precision, 4),
            "word_recall": round(recall, 4),
            "word_f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
            "cer": round(t["char_edits"] / max(t["chars"], 1), 4),
            "cer_in_gold_order": round(t["ordered_char_edits"] / max(t["chars"], 1), 4),
            "wer": round(t["word_edits"] / max(t["wanted"], 1), 4),
        }
    by_kind: dict = {}
    for name, rows in pages.items():
        for kind in sorted({row["kind"] for row in rows}):
            mine = sorted(row["cer"] for row in rows if row["kind"] == kind)
            by_kind.setdefault(name, {})[kind] = {"pages": len(mine), "median_cer": mine[len(mine) // 2]}
    return {"readers": report, "by_kind": by_kind, "splits": [DEV, TEST], "pages": dict(pages)}
