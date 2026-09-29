from __future__ import annotations

from typing import Any

from app.services.gold_annotation import build_annotation_scaffold


def build_annotation_scaffold_batch(
    selection_plan: dict[str, Any],
    page_hash_registry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Join frozen Gold candidates to page hashes and emit review-only DRAFT scaffolds.

    This function deliberately cannot promote annotations to HUMAN_VERIFIED.  It only
    binds candidate identity, layout tags and deterministic rendered-page identity so
    that later machine pre-annotation and human review operate on the exact same page.
    """
    source_sha = selection_plan.get("source_document_sha256")
    if source_sha != page_hash_registry.get("source_document_sha256"):
        raise ValueError("source_document_sha256_mismatch")

    candidates = selection_plan.get("candidates")
    hashes = page_hash_registry.get("pages")
    if not isinstance(candidates, list) or not isinstance(hashes, dict):
        raise TypeError("invalid_gold_assets")

    selected_pages = [candidate.get("pdf_page") for candidate in candidates]
    if len(selected_pages) != 30 or len(set(selected_pages)) != 30:
        raise ValueError("gold_sample_requires_exactly_30_unique_pages")
    if {str(page) for page in selected_pages} != set(hashes):
        raise ValueError("selected_pages_and_hash_registry_must_match")

    scaffolds: list[dict[str, Any]] = []
    for candidate in candidates:
        page_number = candidate.get("pdf_page")
        tags = candidate.get("tags")
        if not isinstance(page_number, int) or not isinstance(tags, list) or not tags:
            raise ValueError("invalid_candidate")

        page_sha = hashes.get(str(page_number))
        if not _is_sha256(page_sha):
            raise ValueError(f"invalid_page_image_sha256:{page_number}")

        scaffold = build_annotation_scaffold(
            sample_id=f"gold-v1-p{page_number:04d}",
            document_sha256=source_sha,
            page_number=page_number,
            layout_tags=tags,
        )
        scaffold["page_image_sha256"] = page_sha
        scaffold["review_notes"] = [
            (
                "DRAFT_SCAFFOLD_ONLY: page identity is frozen; blocks, entries and vocabulary "
                "still require source-grounded annotation and human verification."
            )
        ]
        scaffolds.append(scaffold)

    return scaffolds


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)
