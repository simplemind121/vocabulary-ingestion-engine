from __future__ import annotations

from typing import Any


ALLOWED_TAGS = {
    "NORMAL",
    "DOUBLE_COLUMN",
    "IPA_DENSE",
    "IMAGE",
    "TABLE",
    "INDEX",
    "SPECIAL_LAYOUT",
    "OCR_HARD",
    "BOUNDARY_ENTRY",
    "CROSS_PAGE_ENTRY",
}
SEMANTIC_BOUNDARY_TAGS = {"BOUNDARY_ENTRY", "CROSS_PAGE_ENTRY"}


def validate_selection_plan(plan: dict[str, Any], *, source_page_count: int) -> dict[str, Any]:
    """Validate a pre-Gold candidate plan without treating candidates as verified truth."""
    errors: list[str] = []
    candidates = plan.get("candidates")
    if plan.get("selection_status") != "CANDIDATE_SELECTION":
        errors.append("selection_status must be CANDIDATE_SELECTION")
    if not isinstance(candidates, list):
        errors.append("candidates must be a list")
        candidates = []

    pages: list[int] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            errors.append(f"candidate[{index}] must be an object")
            continue
        page = candidate.get("pdf_page")
        tags = candidate.get("tags")
        reason = candidate.get("reason")
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= source_page_count:
            errors.append(f"candidate[{index}].pdf_page is outside source document")
        else:
            pages.append(page)
        if not isinstance(tags, list) or not tags:
            errors.append(f"candidate[{index}].tags must be a non-empty list")
            tags = []
        unknown = sorted(set(tags) - ALLOWED_TAGS)
        if unknown:
            errors.append(f"candidate[{index}] has unknown tags: {', '.join(unknown)}")
        if SEMANTIC_BOUNDARY_TAGS.intersection(tags):
            if not isinstance(reason, str) or "directly inspected" not in reason.lower():
                errors.append(
                    f"candidate[{index}] semantic boundary tags require direct-inspection evidence"
                )

    if len(pages) != len(set(pages)):
        errors.append("candidate pdf_page values must be unique")

    declared_remaining = plan.get("remaining_slots")
    expected_remaining = max(0, 30 - len(candidates))
    if declared_remaining != expected_remaining:
        errors.append(
            f"remaining_slots must equal 30 - candidate count ({expected_remaining})"
        )
    if len(candidates) > 30:
        errors.append("candidate count cannot exceed the 30-page Gold Sample target")

    return {
        "status": "PASS" if not errors else "FAIL",
        "candidate_count": len(candidates),
        "remaining_slots": expected_remaining,
        "errors": errors,
    }
