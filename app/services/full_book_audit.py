from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import fitz

from app.adapters.pdf_native import PyMuPDFNativeAdapter
from app.models import SourceBlock
from app.services.gold_sample_selection import profile_pdf_pages
from app.services.segmentation import _segment_blocks
from app.services.structured_extraction import parse_source_entry_text

_RISKY_LAYOUT_TAGS = {"TABLE", "INDEX", "SPECIAL_LAYOUT"}


def audit_full_book(
    pdf_path: str | Path,
    *,
    expected_sha256: str,
    expected_page_count: int,
) -> dict[str, Any]:
    """Run a read-only whole-book native extraction and parser audit."""
    source = Path(pdf_path)
    actual_sha = _sha256_file(source)
    if actual_sha != expected_sha256:
        raise ValueError("source_document_sha256_mismatch")

    adapter = PyMuPDFNativeAdapter()
    blocks: list[SourceBlock] = []
    page_numbers: dict[str, int] = {}
    represented_pages: set[int] = set()
    document = fitz.open(source)
    try:
        if document.page_count != expected_page_count:
            raise ValueError("source_document_page_count_mismatch")
        for page_number, page in enumerate(document, start=1):
            page_id = f"page-{page_number}"
            page_numbers[page_id] = page_number
            extracted = adapter.extract_page(page)
            if extracted:
                represented_pages.add(page_number)
            blocks.extend(
                SourceBlock(
                    id=f"native-p{page_number:04d}-b{item.reading_order:04d}",
                    page_id=page_id,
                    processing_run_id="full-book-native-audit",
                    block_type=item.block_type,
                    reading_order=item.reading_order,
                    raw_text=item.text,
                    confidence=item.confidence,
                    bbox=item.bbox.as_dict(),
                    source_engine=adapter.name,
                    source_engine_version=str(adapter.version),
                    metadata_json=item.metadata,
                )
                for item in extracted
            )
    finally:
        document.close()

    profiles = profile_pdf_pages(source)
    tags_by_page = {
        profile["page_number"]: set(profile["candidate_tags"]) for profile in profiles
    }
    candidates = _segment_blocks(blocks, page_numbers)
    review_queue = []
    parsed_count = 0
    for candidate in candidates:
        reasons = []
        try:
            parse_source_entry_text(candidate.raw_text)
            parsed_count += 1
        except ValueError as exc:
            reasons.append(f"STRUCTURED_EXTRACTION_UNCERTAIN:{exc}")
        risky_tags = sorted(
            {
                tag
                for page in candidate.page_numbers
                for tag in tags_by_page.get(page, set()) & _RISKY_LAYOUT_TAGS
            }
        )
        if risky_tags:
            reasons.append("RISKY_LAYOUT:" + ",".join(risky_tags))
        if candidate.confidence < 0.9:
            reasons.append("LOW_SEGMENTATION_CONFIDENCE")
        if reasons:
            review_queue.append(
                {
                    "lemma": candidate.lemma,
                    "page_numbers": candidate.page_numbers,
                    "reasons": reasons,
                    "raw_text_excerpt": candidate.raw_text[:240],
                }
            )

    unrepresented_pages = sorted(set(range(1, expected_page_count + 1)) - represented_pages)
    cross_page = [candidate for candidate in candidates if len(candidate.page_numbers) > 1]
    for page_number in unrepresented_pages:
        review_queue.append(
            {
                "page_numbers": [page_number],
                "reasons": ["NO_TEXT_LAYER"],
                "candidate_values": ["RUN_OCR", "CONFIRM_NON_TEXT_PAGE"],
            }
        )
    status = "REVIEW_REQUIRED" if review_queue else "PASS"
    return {
        "audit_schema_version": "1.0",
        "status": status,
        "source_document_sha256": actual_sha,
        "source_page_count": expected_page_count,
        "native_text_pages": len(represented_pages),
        "native_page_coverage": len(represented_pages) / expected_page_count,
        "unrepresented_pages": unrepresented_pages,
        "source_block_count": len(blocks),
        "entry_candidate_count": len(candidates),
        "parsed_entry_count": parsed_count,
        "cross_page_entry_count": len(cross_page),
        "review_queue_count": len(review_queue),
        "review_queue": review_queue,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
