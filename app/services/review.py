from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Page, ProvenanceRecord, ReviewTask, SourceBlock, VocabularyEntry

OPEN_REVIEW_STATUSES = {"OPEN", "IN_PROGRESS", "ESCALATED"}


def list_review_tasks(db: Session, run_id: str, *, status: str | None = None) -> list[ReviewTask]:
    query = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id)
    if status:
        query = query.filter(ReviewTask.status == status)
    return query.order_by(ReviewTask.created_at, ReviewTask.id).all()


def resolve_review_task(db: Session, task_id: str, *, resolution: dict, reviewer_id: str) -> dict:
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise ValueError("review task not found")
    if task.status not in OPEN_REVIEW_STATUSES:
        raise ValueError("review task is already resolved")
    if task.target_entity_type not in {"VocabularyEntry", "SourceBlock", "Page"}:
        raise ValueError("unsupported review target")
    if not reviewer_id or not reviewer_id.strip():
        raise ValueError("reviewer_id is required")

    decision = str(resolution.get("decision", "ACCEPT")).upper()
    if decision not in {"ACCEPT", "REJECT", "DISCARD"}:
        raise ValueError("review decision must be ACCEPT, REJECT, or DISCARD")
    if decision == "DISCARD" and task.target_entity_type != "SourceBlock":
        raise ValueError("DISCARD is only supported for SourceBlock reviews")

    audit = {
        "decision": decision,
        "reviewer_id": reviewer_id.strip(),
        "resolved_at": datetime.now(UTC).isoformat(),
        "resolution": resolution,
    }
    task.candidate_values = [audit]

    if task.target_entity_type == "Page":
        page = db.get(Page, task.target_entity_id)
        if page is None:
            raise ValueError("review target not found")
        classification = str(resolution.get("classification", "")).upper()
        if decision == "ACCEPT" and classification != "NON_TEXT_PAGE":
            raise ValueError("accepted no-text page requires NON_TEXT_PAGE classification")
        audit["classification"] = classification
        task.status = "RESOLVED" if decision == "ACCEPT" else "ESCALATED"
        db.add(
            ProvenanceRecord(
                processing_run_id=task.processing_run_id,
                target_entity_type="Page",
                target_entity_id=page.id,
                target_field_path="content_classification",
                provenance_type="HUMAN_REVIEW",
                page_id=page.id,
                source_text=classification,
                metadata_json={
                    "review_task_id": task.id,
                    "reviewer_id": reviewer_id.strip(),
                },
            )
        )
        db.commit()
        return {
            "run_id": task.processing_run_id,
            "task_id": task.id,
            "status": task.status,
            "page_id": page.id,
            "verification_status": (
                "HUMAN_VERIFIED" if decision == "ACCEPT" else "REVIEW_REQUIRED"
            ),
            "decision": decision,
            "classification": classification,
        }

    if task.target_entity_type == "SourceBlock":
        block = db.get(SourceBlock, task.target_entity_id)
        if block is None:
            raise ValueError("review target not found")

        corrected_text = (
            None if decision == "DISCARD" else resolution.get("corrected_text")
        )
        if corrected_text is not None:
            corrected_text = str(corrected_text).strip()
            if not corrected_text:
                raise ValueError("corrected_text cannot be empty")
            audit["corrected_text"] = corrected_text

        metadata = dict(block.metadata_json or {})
        metadata["human_ocr_review"] = audit
        if corrected_text is not None:
            # Silver raw_text is immutable evidence. Downstream consumers can
            # explicitly select reviewed_text without losing the OCR observation.
            metadata["reviewed_text"] = corrected_text
        block.metadata_json = metadata

        db.add(
            ProvenanceRecord(
                processing_run_id=task.processing_run_id,
                target_entity_type="SourceBlock",
                target_entity_id=block.id,
                target_field_path="reviewed_text" if corrected_text is not None else "raw_text",
                provenance_type="HUMAN_REVIEW",
                source_block_id=block.id,
                page_id=block.page_id,
                source_text=corrected_text if corrected_text is not None else block.raw_text,
                metadata_json={
                    "review_task_id": task.id,
                    "reviewer_id": reviewer_id.strip(),
                    "raw_ocr_text": block.raw_text,
                },
            )
        )

        if decision in {"ACCEPT", "DISCARD"}:
            task.status = "RESOLVED"
        else:
            task.status = "ESCALATED"
        db.commit()
        return {
            "run_id": task.processing_run_id,
            "task_id": task.id,
            "status": task.status,
            "source_block_id": block.id,
            "verification_status": (
                "HUMAN_DISCARDED"
                if decision == "DISCARD"
                else "HUMAN_VERIFIED"
                if decision == "ACCEPT"
                else "REVIEW_REQUIRED"
            ),
            "decision": decision,
            "reviewed_text": corrected_text,
        }

    entry = db.get(VocabularyEntry, task.target_entity_id)
    if entry is None:
        raise ValueError("review target not found")

    accepted_lemma = resolution.get("lemma")
    if accepted_lemma is not None:
        accepted_lemma = str(accepted_lemma).strip()
        if not accepted_lemma:
            raise ValueError("resolved lemma cannot be empty")
        entry.lemma = accepted_lemma
        db.add(
            ProvenanceRecord(
                processing_run_id=task.processing_run_id,
                target_entity_type="VocabularyEntry",
                target_entity_id=entry.id,
                target_field_path="lemma",
                provenance_type="HUMAN_REVIEW",
                source_entry_id=entry.source_entry_id,
                source_text=accepted_lemma,
                metadata_json={"review_task_id": task.id, "reviewer_id": reviewer_id.strip()},
            )
        )

    if decision == "ACCEPT":
        entry.verification_status = "HUMAN_VERIFIED"
        task.status = "RESOLVED"
        metadata = dict(entry.metadata_json or {})
        metadata["human_verification"] = audit
        entry.metadata_json = metadata
    else:
        entry.verification_status = "REVIEW_REQUIRED"
        task.status = "REJECTED"

    db.commit()
    return {
        "run_id": task.processing_run_id,
        "task_id": task.id,
        "status": task.status,
        "entry_id": entry.id,
        "verification_status": entry.verification_status,
        "decision": decision,
    }
