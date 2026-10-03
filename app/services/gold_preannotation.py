from __future__ import annotations

from typing import Any


def build_machine_annotation_draft(
    scaffold: dict[str, Any],
    prediction: dict[str, Any],
    *,
    generator: str,
) -> dict[str, Any]:
    """Populate a Gold annotation draft from machine output without verifying it."""
    draft = dict(scaffold)
    draft["review_status"] = "DRAFT"
    draft["reviewer_id"] = None
    draft["blocks"] = _copy_items(prediction.get("blocks"))
    draft["entries"] = _copy_items(prediction.get("entries"))
    draft["vocabulary"] = _copy_items(prediction.get("vocabulary"))

    notes = list(draft.get("review_notes") or [])
    notes.append(
        "MACHINE_PREANNOTATION_ONLY: content must be checked against the rendered source page "
        "before HUMAN_VERIFIED promotion."
    )
    notes.append(f"generator={generator}")
    draft["review_notes"] = notes
    return draft


def summarize_review_work(annotation: dict[str, Any]) -> dict[str, Any]:
    """Return a compact checklist for a human reviewer."""
    return {
        "sample_id": annotation.get("sample_id"),
        "page_number": annotation.get("page_number"),
        "review_status": annotation.get("review_status"),
        "block_count": len(annotation.get("blocks") or []),
        "entry_count": len(annotation.get("entries") or []),
        "vocabulary_count": len(annotation.get("vocabulary") or []),
        "checks": [
            "page_identity_and_image_hash",
            "reading_order_and_block_text",
            "entry_boundaries_including_page_edges",
            "lemma_display_form",
            "ipa",
            "part_of_speech",
            "definition",
            "cross_page_continuation",
            "no_machine_added_source_content",
        ],
    }


def _copy_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
