from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import ProvenanceRecord, ReviewTask, SourceBlock, VocabularyEntry

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
    if task.target_entity_type not in {"VocabularyEntry", "SourceBlock"}:
        raise ValueError("unsupported review target")
    if not reviewer_id or not reviewer_id.strip():
        raise ValueError("reviewer_id is required")

    decision = str(resolution.get("decision", "ACCEPT")).upper()
    if decision not in {"ACCEPT", "REJECT"}:
        raise ValueError("review decision must be ACCEPT or REJECT")

    audit = {
        "decision": decision,
        "reviewer_id": reviewer_id.strip(),
        "resolved_at": datetime.now(UTC).isoformat(),
        "resolution": resolution,
    }
    task.candidate_values = [audit]

    if task.target_entity_type == "SourceBlock":
        block = db.get(SourceBlock, task.target_entity_id)
        if block is None:
            raise ValueError("review target not found")
        metadata = dict(block.metadata_json or {})
        metadata["human_ocr_review"] = audit
        block.metadata_json = metadata
        if decision == "ACCEPT":
            task.status = "RESOLVED"
        else:
            # A rejected OCR read remains unresolved. Escalation keeps G1
            # blocked instead of silently allowing uncertain source text onward.
            task.status = "ESCALATED"
        db.commit()
        return {
            "run_id": task.processing_run_id,
            "task_id": task.id,
            "status": task.status,
            "source_block_id": block.id,
            "verification_status": "HUMAN_VERIFIED" if decision == "ACCEPT" else "REVIEW_REQUIRED",
            "decision": decision,
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
