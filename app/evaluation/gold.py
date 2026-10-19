"""Gold pages: structured pages checked by hand against the page image, and their fixed split.

Every fifth unit (by unit number), and every fifth page outside the units (by page
number), is held out as the test set. The split depends only on those numbers, so
it never changes and can be stated in advance.
"""

from __future__ import annotations

import re

DEV, TEST = "dev", "test"


def split_of(tree: dict) -> str:
    key = tree.get("unit") or tree["page"]
    return TEST if int(key) % 5 == 0 else DEV


def page_text(tree: dict) -> str:
    """Everything the page shows, in the tree's reading order, without Markdown marks.

    Handwritten example answers ({{...}}) are printed on the page and stay; empty gaps vanish.
    """
    parts: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("md", "title", "instruction") and isinstance(value, str):
                    parts.append(value)
                elif key in ("items", "subs") and isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            parts.append(item)
                        elif isinstance(item, dict):
                            if item.get("n"):
                                parts.append(str(item["n"]))
                            walk(item)
                elif key == "rows":
                    for row in value or []:
                        parts.extend(cell for cell in row or [] if isinstance(cell, str))
                elif key == "letter" and isinstance(value, str):
                    parts.append(value)
                elif key == "id" and node.get("type") == "exercise":
                    parts.append(str(value))
                elif isinstance(value, (list, dict)) and key not in ("box",):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk({"title": tree.get("title"), "blocks": tree.get("blocks", [])})
    text = " ".join(parts)
    text = re.sub(r"\{\{\}\}", " ", text)
    text = re.sub(r"\{\{|\}\}|\*\*\*|\*\*|~~|__", "", text)
    text = re.sub(r"(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])", "", text)
    return " ".join(text.split())
