from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ProvenanceRecord, ReviewTask, VocabularyEntry


def resolve_review_task(db: Session, task_id: str, *, resolution: dict, reviewer_id: str) -> dict:
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise ValueError("review task not found")
    if task.status not in {"OPEN", "IN_PROGRESS", "ESCALATED"}:
        raise ValueError("review task is already resolved")
    if task.target_entity_type != "VocabularyEntry":
        raise ValueError("unsupported review target")

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
                metadata_json={"review_task_id": task.id, "reviewer_id": reviewer_id},
            )
        )

    entry.verification_status = "HUMAN_VERIFIED"
    task.status = "RESOLVED"
    task.candidate_values = [{"resolution": resolution, "reviewer_id": reviewer_id}]
    db.commit()
    return {"task_id": task.id, "status": task.status, "entry_id": entry.id, "verification_status": entry.verification_status}
