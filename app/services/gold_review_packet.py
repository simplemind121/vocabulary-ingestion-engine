from __future__ import annotations

import hashlib
import html
import json
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    Artifact,
    Definition,
    Page,
    ProcessingRun,
    Pronunciation,
    Sense,
    SourceBlock,
    SourceEntry,
    VocabularyEntry,
)
from app.services.gold_preannotation import summarize_review_work


def build_page_predictions(
    db: Session,
    run_id: str,
    scaffolds: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, Path]]:
    """Project a persisted run onto the exact frozen Gold pages."""
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing_run_not_found")
    requested_pages = {item["page_number"] for item in scaffolds}
    pages = (
        db.query(Page)
        .filter(
            Page.document_version_id == run.document_version_id,
            Page.page_number.in_(requested_pages),
        )
        .all()
    )
    page_by_number = {page.page_number: page for page in pages}
    if set(page_by_number) != requested_pages:
        missing = sorted(requested_pages - set(page_by_number))
        raise ValueError(f"processing_run_missing_gold_pages:{missing}")

    page_ids = {page.id for page in pages}
    blocks = (
        db.query(SourceBlock)
        .filter(
            SourceBlock.processing_run_id == run_id,
            SourceBlock.page_id.in_(page_ids),
        )
        .all()
    )
    blocks_by_page: dict[str, list[SourceBlock]] = {}
    for block in blocks:
        blocks_by_page.setdefault(block.page_id, []).append(block)

    entries = (
        db.query(SourceEntry)
        .filter(SourceEntry.processing_run_id == run_id)
        .order_by(SourceEntry.entry_order, SourceEntry.id)
        .all()
    )
    vocabulary = (
        db.query(VocabularyEntry)
        .filter(VocabularyEntry.processing_run_id == run_id)
        .all()
    )
    vocabulary_by_source = {item.source_entry_id: item for item in vocabulary}

    predictions: list[dict[str, Any]] = []
    image_paths: dict[int, Path] = {}
    scaffold_by_page = {item["page_number"]: item for item in scaffolds}
    for page_number in sorted(requested_pages):
        scaffold = scaffold_by_page[page_number]
        page = page_by_number[page_number]
        artifact = db.get(Artifact, page.render_artifact_id)
        if artifact is None:
            raise ValueError(f"page_render_artifact_missing:{page_number}")
        image_paths[page_number] = Path(artifact.object_key)

        page_blocks = sorted(
            blocks_by_page.get(page.id, []),
            key=lambda item: (item.reading_order if item.reading_order is not None else 10**9, item.id),
        )
        page_entries = [
            entry
            for entry in entries
            if page_number in ((entry.metadata_json or {}).get("pages") or [])
        ]
        predictions.append(
            {
                "document_sha256": scaffold["document_sha256"],
                "page_number": page_number,
                "page_image_sha256": scaffold["page_image_sha256"],
                "blocks": [_serialize_block(block) for block in page_blocks],
                "entries": [_serialize_entry(entry, vocabulary_by_source) for entry in page_entries],
                "vocabulary": [
                    _serialize_vocabulary(db, vocabulary_by_source[entry.id])
                    for entry in page_entries
                    if entry.id in vocabulary_by_source
                ],
            }
        )
    return predictions, image_paths


def write_review_packet(
    drafts: list[dict[str, Any]],
    page_image_paths: dict[int, Path],
    output_dir: str | Path,
) -> dict[str, Any]:
    """Write a private, portable source-vs-machine packet for human sign-off."""
    if len(drafts) != 30:
        raise ValueError("gold_review_packet_requires_exactly_30_drafts")
    output = Path(output_dir)
    image_dir = output / "page-images"
    annotation_dir = output / "annotations"
    image_dir.mkdir(parents=True, exist_ok=True)
    annotation_dir.mkdir(parents=True, exist_ok=True)

    items = []
    for draft in sorted(drafts, key=lambda item: item["page_number"]):
        page = draft["page_number"]
        if draft.get("review_status") != "DRAFT" or draft.get("reviewer_id") is not None:
            raise ValueError(f"review_packet_accepts_draft_only:{page}")
        source_image = Path(page_image_paths.get(page, ""))
        if not source_image.is_file():
            raise ValueError(f"page_image_unavailable:{page}")
        actual_sha = hashlib.sha256(source_image.read_bytes()).hexdigest()
        if actual_sha != draft.get("page_image_sha256"):
            raise ValueError(f"page_image_sha256_mismatch:{page}")

        image_name = f"gold-v1-p{page:04d}{source_image.suffix.lower() or '.png'}"
        shutil.copyfile(source_image, image_dir / image_name)
        annotation_name = f"gold-v1-p{page:04d}.json"
        (annotation_dir / annotation_name).write_text(
            json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        checklist = summarize_review_work(draft)
        flags = _review_flags(draft)
        items.append(
            {
                **checklist,
                "page_image": f"page-images/{image_name}",
                "annotation": f"annotations/{annotation_name}",
                "review_flags": flags,
            }
        )

    manifest = {
        "packet_version": "1.0",
        "review_status": "DRAFT",
        "human_verified_count": 0,
        "page_count": len(items),
        "items": items,
    }
    (output / "packet.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "index.html").write_text(_render_html(drafts, items), encoding="utf-8")
    return manifest


def _serialize_block(block: SourceBlock) -> dict[str, Any]:
    metadata = block.metadata_json or {}
    review = metadata.get("human_ocr_review") or {}
    reviewed = metadata.get("reviewed_text")
    effective_text = reviewed if reviewed and review.get("decision") == "ACCEPT" else block.raw_text
    return {
        "source_block_id": block.id,
        "text": effective_text or "",
        "raw_text": block.raw_text or "",
        "block_type": block.block_type,
        "reading_order": block.reading_order,
        "bbox": block.bbox,
        "confidence": block.confidence,
        "source_engine": block.source_engine,
    }


def _serialize_entry(
    entry: SourceEntry,
    vocabulary_by_source: dict[str, VocabularyEntry],
) -> dict[str, Any]:
    vocab = vocabulary_by_source.get(entry.id)
    return {
        "source_entry_id": entry.id,
        "lemma": vocab.lemma if vocab is not None else "",
        "raw_text": entry.raw_text,
        "entry_order": entry.entry_order,
        "segmentation_confidence": entry.segmentation_confidence,
        "continuation_type": entry.continuation_type,
        "source_pages": (entry.metadata_json or {}).get("pages") or [],
    }


def _serialize_vocabulary(db: Session, item: VocabularyEntry) -> dict[str, Any]:
    pronunciation = (
        db.query(Pronunciation)
        .filter(Pronunciation.vocabulary_entry_id == item.id)
        .order_by(Pronunciation.pronunciation_order)
        .first()
    )
    sense = (
        db.query(Sense)
        .filter(Sense.vocabulary_entry_id == item.id)
        .order_by(Sense.sense_order)
        .first()
    )
    definition = None
    if sense is not None:
        definition = (
            db.query(Definition)
            .filter(Definition.sense_id == sense.id)
            .order_by(Definition.definition_order)
            .first()
        )
    return {
        "vocabulary_entry_id": item.id,
        "source_entry_id": item.source_entry_id,
        "lemma": item.lemma,
        "display_form": item.display_form,
        "ipa": pronunciation.ipa if pronunciation is not None else None,
        "part_of_speech": sense.part_of_speech if sense is not None else None,
        "definition": definition.text if definition is not None else None,
        "machine_verification_status": item.verification_status,
    }


def _review_flags(draft: dict[str, Any]) -> list[str]:
    flags = []
    if not draft.get("blocks"):
        flags.append("NO_BLOCKS")
    if not draft.get("entries"):
        flags.append("NO_ENTRIES")
    if not draft.get("vocabulary"):
        flags.append("NO_VOCABULARY")
    if any((block.get("confidence") or 0) < 0.85 for block in draft.get("blocks") or []):
        flags.append("LOW_OCR_CONFIDENCE")
    if any(entry.get("continuation_type") == "CROSS_PAGE" for entry in draft.get("entries") or []):
        flags.append("CROSS_PAGE_ENTRY")
    for item in draft.get("vocabulary") or []:
        if any(item.get(field) in (None, "") for field in ("ipa", "part_of_speech", "definition")):
            flags.append("MISSING_CANONICAL_FIELD")
            break
    return flags


def _render_html(drafts: list[dict[str, Any]], items: list[dict[str, Any]]) -> str:
    item_by_page = {item["page_number"]: item for item in items}
    cards = []
    for draft in sorted(drafts, key=lambda item: item["page_number"]):
        item = item_by_page[draft["page_number"]]
        flags = " ".join(
            f'<span class="flag">{html.escape(flag)}</span>' for flag in item["review_flags"]
        ) or '<span class="ok">no automatic flags</span>'
        payload = html.escape(json.dumps(draft, ensure_ascii=False, indent=2))
        cards.append(
            f"""<section><h2>{html.escape(draft['sample_id'])} · page {draft['page_number']}</h2>
<p>{flags}</p><div class="compare"><div><h3>Frozen source page</h3>
<img src="{html.escape(item['page_image'])}" alt="source page {draft['page_number']}"></div>
<div><h3>Machine DRAFT — human verification required</h3><pre>{payload}</pre></div></div></section>"""
        )
    return """<!doctype html><html><head><meta charset="utf-8"><title>Gold v1 review packet</title>
<style>body{font:15px system-ui;margin:24px;background:#f5f6f8;color:#18202a}section{background:white;padding:20px;margin:0 0 24px;border-radius:10px}.compare{display:grid;grid-template-columns:minmax(320px,1fr) minmax(320px,1fr);gap:20px}img{max-width:100%;border:1px solid #ccd2da}pre{white-space:pre-wrap;max-height:80vh;overflow:auto;background:#101820;color:#eef5ff;padding:16px}.flag{display:inline-block;background:#fff1cc;color:#714c00;padding:4px 8px;margin:2px;border-radius:12px}.ok{color:#246b3c}@media(max-width:900px){.compare{grid-template-columns:1fr}}</style>
</head><body><h1>Gold Sample v1 — source vs machine review</h1><p>All 30 annotations remain DRAFT. The packet never promotes HUMAN_VERIFIED.</p>""" + "".join(cards) + "</body></html>"
