from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    Page,
    ReviewTask,
    SourceBlock,
    SourceEntry,
    SourceEntryBlock,
    SourceMedia,
    VocabularyEntry,
)


def _page_context(db: Session, page_id: str | None) -> dict | None:
    if not page_id:
        return None
    page = db.get(Page, page_id)
    if page is None:
        return None
    return {
        "id": page.id,
        "page_number": page.page_number,
        "image_url": f"/api/v1/pages/{page.id}/image",
    }


def review_task_detail(db: Session, task: ReviewTask) -> dict:
    payload = {
        "id": task.id,
        "run_id": task.processing_run_id,
        "status": task.status,
        "reason_code": task.reason_code,
        "target_entity_type": task.target_entity_type,
        "target_entity_id": task.target_entity_id,
        "target_field_path": task.target_field_path,
        "source_context": task.source_context,
        "candidate_values": task.candidate_values,
        "created_at": task.created_at.isoformat(),
        "current_value": None,
        "source_text": None,
        "confidence": None,
        "bbox": None,
        "page": None,
    }

    if task.target_entity_type == "Page":
        payload["page"] = _page_context(db, task.target_entity_id)
        payload["current_value"] = task.source_context.get("classification")
        return payload

    if task.target_entity_type == "SourceMedia":
        media = db.get(SourceMedia, task.target_entity_id)
        if media is not None:
            candidates = []
            for entry_id in task.source_context.get("candidate_entry_ids") or []:
                vocabulary = (
                    db.query(VocabularyEntry)
                    .filter(VocabularyEntry.source_entry_id == entry_id)
                    .one_or_none()
                )
                candidates.append(
                    {"source_entry_id": entry_id, "lemma": vocabulary.lemma if vocabulary else None}
                )
            payload.update(
                {
                    "current_value": media.source_entry_id,
                    "verification_status": media.verification_status,
                    "source_text": "; ".join(task.source_context.get("warnings") or []),
                    "confidence": media.confidence,
                    "bbox": media.bbox,
                    "page": _page_context(db, media.page_id),
                    "media_url": f"/api/v1/source-media/{media.id}/content",
                    "media_candidates": candidates,
                }
            )
        return payload

    if task.target_entity_type == "SourceBlock":
        block = db.get(SourceBlock, task.target_entity_id)
        if block is not None:
            payload.update(
                {
                    "current_value": (block.metadata_json or {}).get(
                        "reviewed_text", block.raw_text
                    ),
                    "source_text": block.raw_text,
                    "confidence": block.confidence,
                    "bbox": block.bbox,
                    "page": _page_context(db, block.page_id),
                }
            )
        return payload

    if task.target_entity_type == "VocabularyEntry":
        entry = db.get(VocabularyEntry, task.target_entity_id)
        if entry is None:
            return payload
        source_entry = db.get(SourceEntry, entry.source_entry_id)
        link = (
            db.query(SourceEntryBlock)
            .filter(SourceEntryBlock.source_entry_id == entry.source_entry_id)
            .order_by(SourceEntryBlock.block_order)
            .first()
        )
        block = db.get(SourceBlock, link.source_block_id) if link is not None else None
        payload.update(
            {
                "current_value": entry.lemma,
                "verification_status": entry.verification_status,
                "source_text": source_entry.raw_text if source_entry is not None else None,
                "confidence": (
                    source_entry.segmentation_confidence if source_entry is not None else None
                ),
                "bbox": block.bbox if block is not None else None,
                "page": _page_context(db, block.page_id if block is not None else None),
            }
        )
    return payload
