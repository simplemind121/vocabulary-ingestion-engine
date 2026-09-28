from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import fitz

_LAYOUT_TAGS = (
    "NORMAL",
    "DOUBLE_COLUMN",
    "IPA_DENSE",
    "IMAGE",
    "SPECIAL_LAYOUT",
    "BOUNDARY_ENTRY",
    "CROSS_PAGE_ENTRY",
    "TABLE",
    "INDEX",
    "OCR_HARD",
)

_IPA_CHARS = set("ˈˌəɪʊɛɜɔɑæʌɒθðŋʃʒ")


def profile_pdf_pages(path: str | Path) -> list[dict[str, Any]]:
    document = fitz.open(str(path))
    try:
        profiles: list[dict[str, Any]] = []
        for index, page in enumerate(document):
            text = page.get_text("text") or ""
            blocks = [
                block
                for block in page.get_text("blocks")
                if len(block) >= 5 and isinstance(block[4], str) and block[4].strip()
            ]
            images = page.get_images(full=True)
            width = float(page.rect.width) or 1.0
            x_positions = [float(block[0]) for block in blocks]
            left = sum(x < width * 0.45 for x in x_positions)
            right = sum(x > width * 0.55 for x in x_positions)
            center = len(x_positions) - left - right
            double_column = left >= 3 and right >= 3 and center <= max(3, (left + right) // 4)
            ipa_count = sum(character in _IPA_CHARS for character in text)
            table_signals = sum(
                marker in text
                for marker in (
                    "British",
                    "American",
                    "中文",
                    "词 根",
                    "词缀",
                    "Word List",
                    "索引",
                    "附录",
                )
            )
            text_length = len(text.strip())
            tags = _infer_tags(
                text=text,
                text_length=text_length,
                image_count=len(images),
                block_count=len(blocks),
                double_column=double_column,
                ipa_count=ipa_count,
                table_signals=table_signals,
            )
            profiles.append(
                {
                    "page_number": index + 1,
                    "text_length": text_length,
                    "block_count": len(blocks),
                    "image_count": len(images),
                    "ipa_count": ipa_count,
                    "double_column": double_column,
                    "table_signals": table_signals,
                    "candidate_tags": tags,
                }
            )
        return profiles
    finally:
        document.close()


def select_gold_sample_candidates(
    profiles: list[dict[str, Any]],
    *,
    target_pages: int = 30,
) -> list[dict[str, Any]]:
    if target_pages < len(_LAYOUT_TAGS):
        raise ValueError("target_pages must allow at least one page per required layout tag")

    selected: dict[int, dict[str, Any]] = {}
    coverage = Counter()

    for tag in _LAYOUT_TAGS:
        candidates = [profile for profile in profiles if tag in profile["candidate_tags"]]
        if not candidates:
            continue
        candidate = max(candidates, key=lambda profile: _score(profile, tag))
        selected[candidate["page_number"]] = candidate
        coverage.update([tag])

    remaining = sorted(
        profiles,
        key=lambda profile: (
            _diversity_score(profile, coverage),
            profile["ipa_count"],
            profile["block_count"],
            profile["text_length"],
        ),
        reverse=True,
    )
    for profile in remaining:
        if len(selected) >= target_pages:
            break
        if profile["page_number"] in selected:
            continue
        selected[profile["page_number"]] = profile
        coverage.update(profile["candidate_tags"])

    return [
        {
            **profile,
            "selection_status": "CANDIDATE_SELECTION",
            "requires_visual_review": True,
        }
        for profile in sorted(selected.values(), key=lambda item: item["page_number"])
    ]


def summarize_candidate_coverage(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    covered = sorted(
        {
            tag
            for candidate in candidates
            for tag in candidate.get("candidate_tags", [])
            if tag in _LAYOUT_TAGS
        }
    )
    return {
        "candidate_count": len(candidates),
        "covered_layout_tags": covered,
        "missing_layout_tags": sorted(set(_LAYOUT_TAGS) - set(covered)),
    }


def _infer_tags(
    *,
    text: str,
    text_length: int,
    image_count: int,
    block_count: int,
    double_column: bool,
    ipa_count: int,
    table_signals: int,
) -> list[str]:
    tags: set[str] = set()
    if text_length >= 500 and block_count >= 5:
        tags.add("NORMAL")
    if double_column:
        tags.add("DOUBLE_COLUMN")
    if ipa_count >= 20:
        tags.add("IPA_DENSE")
    if image_count:
        tags.add("IMAGE")
    if table_signals >= 2:
        tags.add("TABLE")
    if "索引" in text or "Index" in text:
        tags.add("INDEX")
    if "Word List" in text or table_signals >= 3:
        tags.add("SPECIAL_LAYOUT")
    if text_length <= 50 and image_count:
        tags.add("OCR_HARD")
    if text.strip() and not text.endswith("\n"):
        tags.add("BOUNDARY_ENTRY")
    return sorted(tags)


def _score(profile: dict[str, Any], tag: str) -> tuple[int, int, int]:
    return (
        1 if tag in profile["candidate_tags"] else 0,
        int(profile["ipa_count"]),
        int(profile["block_count"]),
    )


def _diversity_score(profile: dict[str, Any], coverage: Counter[str]) -> int:
    return sum(10 if coverage[tag] == 0 else max(1, 5 - coverage[tag]) for tag in profile["candidate_tags"])
