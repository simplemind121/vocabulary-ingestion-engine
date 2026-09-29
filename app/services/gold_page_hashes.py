from __future__ import annotations

import re
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_RENDER_CONTRACT = {
    "engine": "PyMuPDF",
    "matrix": [2, 2],
    "dpi": 144,
    "alpha": False,
    "format": "png",
}


def validate_page_hash_registry(
    registry: dict[str, Any],
    *,
    selection_plan: dict[str, Any],
) -> dict[str, Any]:
    """Fail closed unless deterministic render hashes exactly cover selected Gold pages."""
    errors: list[str] = []

    if registry.get("source_document_sha256") != selection_plan.get("source_document_sha256"):
        errors.append("source document SHA256 does not match selection plan")
    if registry.get("render_contract") != _EXPECTED_RENDER_CONTRACT:
        errors.append("render contract does not match frozen Gold Sample render contract")

    candidates = selection_plan.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
        errors.append("selection plan candidates must be a list")
    selected_pages = {
        str(candidate.get("pdf_page"))
        for candidate in candidates
        if isinstance(candidate, dict) and isinstance(candidate.get("pdf_page"), int)
    }

    pages = registry.get("pages")
    if not isinstance(pages, dict):
        pages = {}
        errors.append("pages must be an object")

    hashed_pages = set(pages)
    missing = sorted(selected_pages - hashed_pages, key=int)
    extra = sorted(hashed_pages - selected_pages, key=lambda value: int(value) if value.isdigit() else -1)
    if missing:
        errors.append(f"missing page hashes: {', '.join(missing)}")
    if extra:
        errors.append(f"unselected page hashes present: {', '.join(extra)}")

    invalid = sorted(
        page for page, digest in pages.items() if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest)
    )
    if invalid:
        errors.append(f"invalid SHA256 digests for pages: {', '.join(invalid)}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "selected_page_count": len(selected_pages),
        "hashed_page_count": len(pages),
        "errors": errors,
    }
