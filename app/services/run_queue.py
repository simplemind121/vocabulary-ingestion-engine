from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import ProcessingRun

ACTIVE_RUN_STATUSES = {"QUEUED", "STARTING", "RUNNING"}
QUEUEABLE_RUN_STATUSES = {
    "FAILED",
    "OCR_REQUIRED",
    "QUEUE_FAILED",
    "READY",
    "REVIEW_REQUIRED",
}


def queue_processing_run(
    db: Session,
    run_id: str,
    *,
    dispatch: Callable[[str, str], None],
) -> dict:
    run = (
        db.query(ProcessingRun)
        .filter(ProcessingRun.id == run_id)
        .with_for_update()
        .one_or_none()
    )
    if run is None:
        raise ValueError("processing run not found")
    if run.status in ACTIVE_RUN_STATUSES:
        raise ValueError(f"processing run is already active: {run.status}")
    if run.status not in QUEUEABLE_RUN_STATUSES:
        raise ValueError(f"processing run cannot be queued from status: {run.status}")

    task_id = str(uuid.uuid4())
    previous_status = run.status
    queued_at = datetime.now(UTC).isoformat()
    run.status = "QUEUED"
    run.finished_at = None
    run.error_summary = None
    run.metrics = {
        **(run.metrics or {}),
        "queue_task_id": task_id,
        "queued_at": queued_at,
        "queued_from_status": previous_status,
    }
    db.commit()

    try:
        dispatch(run_id, task_id)
    except Exception as exc:
        failed = (
            db.query(ProcessingRun)
            .filter(ProcessingRun.id == run_id)
            .with_for_update()
            .one()
        )
        if (failed.metrics or {}).get("queue_task_id") == task_id and failed.status == "QUEUED":
            failed.status = "QUEUE_FAILED"
            failed.finished_at = datetime.now(UTC)
            failed.error_summary = {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "stage": "queue_dispatch",
            }
            db.commit()
        raise RuntimeError("pipeline queue is unavailable") from exc

    return {
        "run_id": run_id,
        "status": "QUEUED",
        "task_id": task_id,
        "queued_at": queued_at,
    }


def claim_queued_run(db: Session, run_id: str, *, task_id: str) -> tuple[bool, str]:
    run = (
        db.query(ProcessingRun)
        .filter(ProcessingRun.id == run_id)
        .with_for_update()
        .one_or_none()
    )
    if run is None:
        raise ValueError("processing run not found")
    expected_task = (run.metrics or {}).get("queue_task_id")
    if run.status != "QUEUED" or expected_task != task_id:
        return False, run.status
    run.status = "STARTING"
    run.metrics = {
        **(run.metrics or {}),
        "worker_claimed_at": datetime.now(UTC).isoformat(),
    }
    db.commit()
    return True, "STARTING"


def fail_claimed_run(db: Session, run_id: str, *, exc: Exception) -> None:
    run = db.get(ProcessingRun, run_id)
    if run is None or run.status != "STARTING":
        return
    run.status = "FAILED"
    run.finished_at = datetime.now(UTC)
    run.error_summary = {
        "error_type": type(exc).__name__,
        "message": str(exc),
        "stage": "worker_start",
    }
    db.commit()
