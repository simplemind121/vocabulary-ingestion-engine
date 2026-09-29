from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import fitz

from app.adapters.pdf_native import PyMuPDFNativeAdapter
from app.models import SourceBlock
from app.services.gold_page_hashes import GOLD_RENDER_CONTRACT
from app.services.segmentation import SegmentCandidate, _segment_blocks
from app.services.structured_extraction import parse_source_entry_text


def build_native_pdf_predictions(
    pdf_path: str | Path,
    scaffolds: list[dict[str, Any]],
    render_dir: str | Path,
) -> tuple[list[dict[str, Any]], dict[int, Path]]:
    """Run production native extraction/segmentation directly on frozen Gold pages."""
    source = Path(pdf_path)
    actual_source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    expected_source_hashes = {item.get("document_sha256") for item in scaffolds}
    if expected_source_hashes != {actual_source_sha}:
        raise ValueError("source_document_sha256_mismatch")

    target = Path(render_dir)
    target.mkdir(parents=True, exist_ok=True)
    adapter = PyMuPDFNativeAdapter()
    page_numbers = sorted(item["page_number"] for item in scaffolds)
    scaffold_by_page = {item["page_number"]: item for item in scaffolds}
    if len(scaffold_by_page) != len(scaffolds):
        raise ValueError("scaffold_pages_must_be_unique")

    blocks_by_page: dict[int, list[SourceBlock]] = {}
    image_paths: dict[int, Path] = {}
    document = fitz.open(source)
    try:
        if not page_numbers or page_numbers[-1] > document.page_count:
            raise ValueError("selected_page_out_of_range")
        for page_number in page_numbers:
            pdf_page = document[page_number - 1]
            image_path = target / f"gold-v1-p{page_number:04d}.png"
            matrix = GOLD_RENDER_CONTRACT["matrix"]
            pdf_page.get_pixmap(matrix=fitz.Matrix(*matrix), alpha=False).save(image_path)
            actual_page_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if actual_page_sha != scaffold_by_page[page_number].get("page_image_sha256"):
                raise ValueError(f"page_image_sha256_mismatch:{page_number}")
            image_paths[page_number] = image_path
            blocks_by_page[page_number] = [
                SourceBlock(
                    id=f"native-p{page_number:04d}-b{block.reading_order:04d}",
                    page_id=f"page-{page_number}",
                    processing_run_id="gold-native-preannotation",
                    block_type=block.block_type,
                    reading_order=block.reading_order,
                    raw_text=block.text,
                    confidence=block.confidence,
                    bbox=block.bbox.as_dict(),
                    source_engine=adapter.name,
                    source_engine_version=str(adapter.version),
                    metadata_json=block.metadata,
                )
                for block in adapter.extract_page(pdf_page)
            ]
    finally:
        document.close()

    candidates = _segment_contiguous_page_groups(page_numbers, blocks_by_page)
    predictions = []
    for page_number in page_numbers:
        page_candidates = [item for item in candidates if page_number in item.page_numbers]
        predictions.append(
            {
                "document_sha256": actual_source_sha,
                "page_number": page_number,
                "page_image_sha256": scaffold_by_page[page_number]["page_image_sha256"],
                "blocks": [_serialize_native_block(block) for block in blocks_by_page[page_number]],
                "entries": [_serialize_candidate(item) for item in page_candidates],
                "vocabulary": [_parse_candidate(item) for item in page_candidates],
            }
        )
    return predictions, image_paths


def _segment_contiguous_page_groups(
    page_numbers: list[int],
    blocks_by_page: dict[int, list[SourceBlock]],
) -> list[SegmentCandidate]:
    candidates: list[SegmentCandidate] = []
    group: list[int] = []
    for page_number in page_numbers:
        if group and page_number != group[-1] + 1:
            candidates.extend(_segment_page_group(group, blocks_by_page))
            group = []
        group.append(page_number)
    if group:
        candidates.extend(_segment_page_group(group, blocks_by_page))
    return candidates


def _segment_page_group(
    page_numbers: list[int],
    blocks_by_page: dict[int, list[SourceBlock]],
) -> list[SegmentCandidate]:
    blocks = [block for page in page_numbers for block in blocks_by_page[page]]
    page_by_id = {f"page-{page}": page for page in page_numbers}
    return _segment_blocks(blocks, page_by_id)


def _serialize_native_block(block: SourceBlock) -> dict[str, Any]:
    return {
        "source_block_id": block.id,
        "text": block.raw_text or "",
        "raw_text": block.raw_text or "",
        "block_type": block.block_type,
        "reading_order": block.reading_order,
        "bbox": block.bbox,
        "confidence": block.confidence,
        "source_engine": block.source_engine,
    }


def _serialize_candidate(item: SegmentCandidate) -> dict[str, Any]:
    return {
        "lemma": item.lemma,
        "raw_text": item.raw_text,
        "segmentation_confidence": item.confidence,
        "continuation_type": "CROSS_PAGE" if len(item.page_numbers) > 1 else None,
        "source_pages": item.page_numbers,
        "source_block_ids": item.block_ids,
    }


def _parse_candidate(item: SegmentCandidate) -> dict[str, Any]:
    try:
        parsed = parse_source_entry_text(item.raw_text)
    except ValueError as exc:
        return {
            "lemma": item.lemma,
            "display_form": item.lemma,
            "ipa": None,
            "part_of_speech": None,
            "definition": None,
            "machine_verification_status": "REVIEW_REQUIRED",
            "parsing_error": str(exc),
        }
    return {
        "lemma": parsed.lemma,
        "display_form": parsed.lemma,
        "ipa": parsed.ipa,
        "part_of_speech": parsed.part_of_speech,
        "definition": parsed.definition,
        "machine_verification_status": "PARSED",
    }
