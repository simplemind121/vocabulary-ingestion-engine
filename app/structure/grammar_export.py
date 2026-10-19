"""The grammar-textbook profile: units of explanation and exercise pages, parts, and answer keys.

A book profile (JSON, kept with the book) names the book and its divisions:

  {"id": "egu", "name": "...", "nameEn": "...",
   "groups": [["Present and past", "现在与过去", 1, 6], ...],            units grouped by topic
   "parts": [["key", "Key to Exercises", "练习答案", 347, 378], ...],   page ranges outside the units
   "keys": {"key": {"pages": [347, 378], "heading": "\\\\*\\\\*(\\\\d+\\\\.\\\\d+)\\\\*\\\\*"}, ...}}

Each answer key is gathered from its pages: a bold heading line matching
``heading`` starts an exercise's answers, and the blocks after it belong to it.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from app.structure.figures import cut_figures


def _flat(blocks: list):
    """The blocks of a key page in reading order, columns one after another."""
    for block in blocks:
        if block.get("type") == "columns":
            for column in block["columns"]:
                yield from _flat(column)
        elif block.get("type") == "box":
            yield from _flat(block.get("blocks", []))
        else:
            yield block


def _gather(pages: dict, first: int, last: int, heading: str) -> dict:
    keys, current = {}, None
    for number in range(first, last + 1):
        if number not in pages:
            continue
        for block in _flat(pages[number]["blocks"]):
            text = (block.get("md") or "").strip() if block.get("type") == "text" else ""
            found = re.fullmatch(heading, text)
            if found:
                current = found.group(1)
                keys.setdefault(current, [])
            elif re.fullmatch(r"\*\*UNIT \d+\*\*", text):
                continue
            elif current:
                keys[current].append(block)
    return keys


def _attach(blocks: list, pictures: list, counter: list) -> None:
    for block in blocks:
        kind = block.get("type")
        if kind == "figure":
            if counter[0] < len(pictures):
                block["src"], block["width"] = pictures[counter[0]]["src"], pictures[counter[0]]["width"]
            counter[0] += 1
        elif kind in ("section", "box", "exercise"):
            _attach(block.get("blocks", []), pictures, counter)
        elif kind == "columns":
            for column in block.get("columns", []):
                _attach(column, pictures, counter)


def build_book(trees: dict[int, dict], profile: dict, pictures: dict[int, list]) -> dict:
    """The reading site's book: every page, the units, the parts and the answer keys."""
    pages = {}
    for number in sorted(trees):
        tree = copy.deepcopy(trees[number])
        _attach(tree["blocks"], pictures.get(number, []), [0])
        pages[number] = {"kind": tree.get("kind", "other"), "unit": tree.get("unit"), "title": tree.get("title"), "blocks": tree["blocks"]}

    units: dict[int, dict] = {}
    for number, page in pages.items():
        if page["kind"] in ("unit-explanation", "unit-exercises") and page["unit"]:
            unit = units.setdefault(page["unit"], {"unit": page["unit"], "title": None, "explain": [], "exercises": []})
            if page["kind"] == "unit-explanation":
                unit["explain"].append(number)
                unit["title"] = unit["title"] or page["title"]
            else:
                unit["exercises"].append(number)

    book = {
        "id": profile["id"],
        "name": profile["name"],
        "nameEn": profile["nameEn"],
        "groups": [{"en": en, "zh": zh, "first": a, "last": b} for en, zh, a, b in profile["groups"]],
        "parts": [{"id": i, "en": en, "zh": zh, "first": a, "last": b} for i, en, zh, a, b in profile["parts"]],
        "units": [units[u] for u in sorted(units)],
        "pages": {str(n): p for n, p in pages.items()},
    }
    for name, key in profile.get("keys", {}).items():
        book[name] = _gather(pages, key["pages"][0], key["pages"][1], key["heading"])
    return book


def export_grammar(trees: dict[int, dict], pdf_path: str | Path, profile: dict, out_dir: str | Path) -> dict:
    """Write ``grammar.json`` and the cut pictures (``fig/``) for the reading site."""
    import fitz

    out = Path(out_dir)
    (out / "fig").mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as document:
        pictures = {n: cut_figures(document, n, trees[n]["blocks"], out / "fig") for n in sorted(trees)}
    book = build_book(trees, profile, pictures)
    (out / "grammar.json").write_text(json.dumps(book, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {
        "pages": len(book["pages"]),
        "units": len(book["units"]),
        "pictures": sum(len(p) for p in pictures.values()),
        **{f"{name}_exercises": len(book[name]) for name in profile.get("keys", {})},
    }
