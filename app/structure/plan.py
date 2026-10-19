"""Page plans: a short text a person writes beside the page image, compiled to a page tree.

A plan is one directive per line. Text is either line references taken from the
page's voted lines (L3, L3-5, L3+L5) or literal text, which must only use words
the readers read on that page (anything inside {{ }} is a gap or a handwritten
answer). Append " b=phrase;phrase" to line references to bold those phrases.

  K explain 6 | Past continuous (**I was doing**)    page kind, unit, title
  K exercises 6           K other
  S A                     start lettered section A
  P <text>                paragraph
  X <text> | <text> ...   example sentences
  T a;b / c;d             table: rows split by " / ", cells by ";"
  C   |C   /C             start columns, next column, end columns
  B   /B                  start and end a shaded panel
  F x1 y1 x2 y2 about     figure (rough box; snapped to the picture found on the page)
  F= x1 y1 x2 y2 about    figure cut exactly at the given box
  E 6.1 <text>            exercise with its instruction
  W a|b|c                 word bank
  I 3 <text>              exercise item 3
  R <text>                cross-reference
  N <text> / N- <text>    index entry and its indented sub-entries
  - 1,2                   lines deliberately left out (page number, running header)

In literal text, " // " is a line break inside the same block.

Two checks run on every plan. "invented": words in literal text that no reader
read on the page. "dropped_lines": voted lines neither referenced, nor left out
on purpose, nor covered by the literal text.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from app.structure.evidence import WORD, readable_words

KINDS = {"explain": "unit-explanation", "exercises": "unit-exercises"}


def compile_plan(number: int, plan: str, lines: list[dict], text_layer: Iterable[str] = (), *, by: str) -> dict:
    """The page tree for page ``number``, with the checks under ``checked``."""
    used: set[int] = set()
    literal: list[str] = []

    def text(spec: str) -> str:
        spec = spec.strip()
        bold = []
        if " b=" in spec and re.match(r"L\d", spec):
            spec, _, phrases = spec.partition(" b=")
            bold = [p.strip() for p in phrases.split(";") if p.strip()]
        mixed = re.fullmatch(r"(L\d+(?:-\d+)?(?:\+L\d+(?:-\d+)?)*)\s+(\S.*)", spec)
        if mixed and not bold:
            # Lines from the OCR followed by literal text, typically a gap: "L33 {{}}".
            return text(mixed.group(1)) + " " + text(mixed.group(2))
        if re.fullmatch(r"L\d+(-\d+)?(\+L\d+(-\d+)?)*", spec):
            parts = []
            for piece in spec.split("+"):
                start, _, end = piece[1:].partition("-")
                for i in range(int(start), int(end or start) + 1):
                    used.add(i)
                    parts.append(lines[i - 1]["text"])
            out = " ".join(parts)
            for phrase in bold:
                if phrase in out:
                    out = out.replace(phrase, f"**{phrase}**", 1)
                else:
                    raise ValueError(f"bold phrase not found: {phrase!r} in {out!r}")
            return out
        literal.append(spec)
        # " // " marks a line break inside one block (several answers to one key item).
        return spec.replace(" // ", "  \n")

    root: list = []
    stack: list[list] = [root]
    data = {"page": number, "kind": "other", "unit": None, "title": None, "blocks": root}
    columns = None
    for raw in plan.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        op, _, rest = line.partition(" ")
        if op == "K":
            head, _, title = rest.partition("|")
            parts = head.split()
            data["kind"] = KINDS.get(parts[0], "other")
            data["unit"] = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            data["title"] = text(title) if title.strip() else None
        elif op == "S":
            section = {"type": "section", "letter": rest.strip(), "blocks": []}
            root.append(section)
            stack = [root, section["blocks"]]
        elif op == "E":
            number_, _, instruction = rest.partition(" ")
            exercise = {"type": "exercise", "id": number_, "instruction": text(instruction), "blocks": []}
            root.append(exercise)
            stack = [root, exercise["blocks"]]
        elif op == "C":
            columns = {"type": "columns", "columns": [[]]}
            stack[-1].append(columns)
            stack.append(columns["columns"][0])
        elif op == "|C":
            stack.pop()
            columns["columns"].append([])
            stack.append(columns["columns"][-1])
        elif op == "/C":
            stack.pop()
        elif op == "B":
            box = {"type": "box", "blocks": []}
            stack[-1].append(box)
            stack.append(box["blocks"])
        elif op == "/B":
            stack.pop()
        elif op == "P":
            stack[-1].append({"type": "text", "md": text(rest)})
        elif op == "X":
            stack[-1].append({"type": "examples", "items": [text(p) for p in rest.split(" | ")]})
        elif op == "T":
            stack[-1].append({"type": "table", "rows": [[text(c) for c in row.split(";")] for row in rest.split(" / ")]})
        elif op in ("F", "F="):
            x1, y1, x2, y2, *about = rest.split()
            figure = {"type": "figure", "box": [float(x1), float(y1), float(x2), float(y2)], "about": " ".join(about)}
            if op == "F=":
                figure["exact"] = True
            stack[-1].append(figure)
        elif op == "W":
            stack[-1].append({"type": "words", "items": [text(p) for p in rest.split("|")]})
        elif op == "I":
            n, _, body = rest.partition(" ")
            target = stack[-1]
            if not (target and target[-1].get("type") == "items"):
                target.append({"type": "items", "items": []})
            body = text(body)
            # An item taken from an OCR line still starts with its own number.
            body = re.sub(rf"^{re.escape(n)}\s*(?=\S)", "", body)
            target[-1]["items"].append({"n": n, "md": body})
        elif op == "N":
            # Index entry: "N head" then "N- sub" lines for its indented sub-entries.
            stack[-1].append({"type": "entry", "md": text(rest), "subs": []})
        elif op == "N-":
            if not (stack[-1] and stack[-1][-1].get("type") == "entry"):
                # Sub-entries continued at the top of a new column.
                stack[-1].append({"type": "entry", "md": "", "subs": []})
            stack[-1][-1]["subs"].append(text(rest))
        elif op == "R":
            stack[-1].append({"type": "refs", "md": text(rest)})
        elif op == "-":
            for piece in rest.split(","):
                start, _, end = piece.strip().partition("-")
                used.update(range(int(start), int(end or start) + 1))
        else:
            raise ValueError(f"unknown directive: {raw!r}")

    data["checked"] = {**check(literal, used, lines, text_layer), "by": by}
    return data


def check(literal: list[str], used: set[int], lines: list[dict], text_layer: Iterable[str] = ()) -> dict:
    """Nothing invented, nothing silently dropped."""
    readable = readable_words(lines, text_layer)
    invented = sorted(
        {
            w
            for s in literal
            for w in WORD.findall(re.sub(r"\{\{.*?\}\}", " ", s).replace("*", "").replace("~", "").replace("__", ""))
            if w.lower() not in readable
        }
    )
    literal_words = Counter(w.lower() for s in literal for w in WORD.findall(s))
    letters = re.sub(r"[^a-z]", "", " ".join(literal).lower())
    dropped = []
    for i, line in enumerate(lines, 1):
        if i in used:
            continue
        found = [w.lower() for w in WORD.findall(line["text"])]
        # Merged OCR words ("3opens", "aren'tspeaking") are found by their letters alone.
        if found and sum(1 for w in found if literal_words[w] > 0 or re.sub(r"[^a-z]", "", w) in letters) < 0.6 * len(found):
            dropped.append(f"{i}:{line['text'][:50]}")
    return {"invented": invented, "dropped_lines": dropped}
