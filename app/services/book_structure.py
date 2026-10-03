from __future__ import annotations

import re
from dataclasses import dataclass

_WORD_LIST = re.compile(r"^\s*Word\s+List\s+(\d+)\s*$", re.IGNORECASE)
_HEADWORD = re.compile(
    r"^\s*([A-Za-z][A-Za-z'’-]*(?:-[A-Za-z][A-Za-z'’-]*)?)"
    r"(\*)?\s+\[([^\]]+)\]"
)
# Words with several pronunciations (or none printed) put the headword alone on
# its own bold line; the IPA and part of speech follow on the next lines.
_BARE_HEADWORD = re.compile(r"^\s*([A-Za-z][A-Za-z'’-]*)(\*)?\s*$")
_FIELD_MARKER = re.compile(r"^\s*([记搭例派同反])(?:\s|$)")
_PAGE_NUMBER = re.compile(r"^\s*\d{1,4}\s*$")
_NON_ENTRY_SECTION = re.compile(r"^[一二三四五六七八九十]+\s+雅思")
_PREVIEW_MARKERS = ("词根/词缀预习表", "词根/词", "缀", "含义", "例词及释义")


@dataclass(slots=True)
class BookBlockClassification:
    block_type: str
    confidence: float
    metadata: dict


def classify_book_text(text: str, *, in_preview_table: bool = False) -> BookBlockClassification:
    normalized = " ".join((text or "").split())
    if not normalized:
        return BookBlockClassification("EMPTY", 1.0, {})

    word_list = _WORD_LIST.match(normalized)
    if word_list:
        return BookBlockClassification(
            "WORD_LIST_HEADER", 0.99, {"word_list": int(word_list.group(1))}
        )

    if normalized == "词根/词缀预习表":
        return BookBlockClassification("PREVIEW_TABLE_HEADER", 0.99, {})

    if _NON_ENTRY_SECTION.match(normalized) or normalized.upper() == "INDEX":
        return BookBlockClassification("NON_ENTRY_SECTION_HEADER", 0.99, {})

    # A canonical headword+IPA line is strong enough evidence to terminate
    # preview-table context. Plain English rows inside the table do not match.
    headword = _HEADWORD.match(normalized)
    if headword:
        return BookBlockClassification(
            "ENTRY_HEAD",
            0.98,
            {
                "lemma": headword.group(1),
                "starred": bool(headword.group(2)),
                "ipa": headword.group(3),
            },
        )

    if in_preview_table or any(normalized == marker for marker in _PREVIEW_MARKERS):
        return BookBlockClassification("PREVIEW_TABLE", 0.95, {})

    field = _FIELD_MARKER.match(normalized)
    if field:
        return BookBlockClassification(
            "ENTRY_FIELD", 0.96, {"field_marker": field.group(1)}
        )

    if _PAGE_NUMBER.match(normalized):
        return BookBlockClassification("PAGE_NUMBER", 0.98, {})

    if normalized in {"音频", "影视剧场景"}:
        return BookBlockClassification("DECORATION", 0.98, {})

    return BookBlockClassification("BODY_TEXT", 0.60, {})


def bare_headword(text: str) -> tuple[str, bool] | None:
    """Return (lemma, starred) for a headword printed without inline IPA."""
    match = _BARE_HEADWORD.match(" ".join((text or "").split()))
    if match is None:
        return None
    return match.group(1), bool(match.group(2))


def is_entry_head(text: str) -> bool:
    return classify_book_text(text).block_type == "ENTRY_HEAD"
