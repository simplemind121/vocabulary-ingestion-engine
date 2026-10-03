from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.book_structure import bare_headword, classify_book_text

_HEAD = re.compile(
    r"^\s*(?P<lemma>[A-Za-z][A-Za-z'’-]*(?:-[A-Za-z][A-Za-z'’-]*)?)"
    r"(?P<star>\*)?\s+\[(?P<ipa>[^\]]+)\]\s*(?P<body>.*)$"
)
_LEADING_IPA = re.compile(r"^\[(?P<ipa>[^\]]+)\]\s*(?P<body>.*)$")
_POS_TOKEN = r"(?:n|v|vt|vi|adj|adv|prep|conj|pron|num|art)\."
_POS = re.compile(
    rf"^(?P<pos>{_POS_TOKEN}(?:/{_POS_TOKEN})*)\s*(?P<definition>.*)$"
)
_MARKERS = {"记": "memory_notes", "搭": "collocations", "例": "examples", "派": "derivatives", "同": "synonyms", "反": "antonyms"}


@dataclass(slots=True)
class ParsedSourceEntry:
    lemma: str
    starred: bool
    ipa: str | None
    pronunciations: list[str] = field(default_factory=list)
    senses: list[dict] = field(default_factory=list)
    memory_notes: list[str] = field(default_factory=list)
    collocations: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    derivatives: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    antonyms: list[str] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)


def parse_source_entry(lines: list[str]) -> ParsedSourceEntry:
    clean = [" ".join(line.split()) for line in lines if line and line.strip()]
    if not clean:
        raise ValueError("entry has no source text")
    match = _HEAD.match(clean[0])
    bare = None if match else bare_headword(clean[0])
    if match:
        parsed = ParsedSourceEntry(
            lemma=match.group("lemma"),
            starred=bool(match.group("star")),
            ipa=match.group("ipa"),
            pronunciations=[match.group("ipa")],
        )
        pending = match.group("body").strip()
    elif bare:
        parsed = ParsedSourceEntry(lemma=bare[0], starred=bare[1], ipa=None)
        pending = ""
    else:
        raise ValueError("entry does not begin with a headword source line")
    active_field: str | None = None
    if pending:
        _consume_unmarked(parsed, pending)

    for line in clean[1:]:
        classification = classify_book_text(line)
        if classification.block_type == "ENTRY_FIELD":
            marker = classification.metadata["field_marker"]
            active_field = _MARKERS[marker]
            payload = line.lstrip()[1:].strip()
            if payload:
                getattr(parsed, active_field).append(payload)
            continue
        if classification.block_type in {
            "WORD_LIST_HEADER",
            "PREVIEW_TABLE_HEADER",
            "PREVIEW_TABLE",
            "PAGE_NUMBER",
            "DECORATION",
        }:
            continue
        if active_field:
            values = getattr(parsed, active_field)
            if values:
                values[-1] = f"{values[-1]} {line}".strip()
            else:
                values.append(line)
        else:
            _consume_unmarked(parsed, line)
    return parsed


def _consume_unmarked(parsed: ParsedSourceEntry, text: str) -> None:
    leading_ipa = _LEADING_IPA.match(text)
    if leading_ipa and not (
        # "[pl.] 配件" is a wrapped usage label, not a pronunciation.
        not leading_ipa.group("body").strip() or _POS.match(leading_ipa.group("body").strip())
    ):
        leading_ipa = None
    if leading_ipa:
        # One pronunciation per line, each followed by the senses it governs.
        parsed.pronunciations.append(leading_ipa.group("ipa"))
        if parsed.ipa is None:
            parsed.ipa = leading_ipa.group("ipa")
        text = leading_ipa.group("body").strip()
        if not text:
            return
    pos = _POS.match(text)
    if pos:
        parsed.senses.append(
            {"pos": pos.group("pos"), "definition": pos.group("definition").strip()}
        )
    elif parsed.senses:
        sense = parsed.senses[-1]
        definition = sense["definition"]
        sense["definition"] = _join_wrapped_text(definition, text)
    else:
        parsed.unclassified.append(text)


def _join_wrapped_text(previous: str, continuation: str) -> str:
    if not previous:
        return continuation
    if not continuation:
        return previous
    if _is_cjk_or_cjk_punctuation(previous[-1]) or _is_cjk_or_cjk_punctuation(continuation[0]):
        return previous + continuation
    return f"{previous} {continuation}"


def _is_cjk_or_cjk_punctuation(char: str) -> bool:
    return "\u3400" <= char <= "\u9fff" or char in "，。；：！？、（）【】《》“”‘’"
