from __future__ import annotations

from celery import Celery

from app.db import SessionLocal
from app.services.extraction import extract_native_blocks
from app.services.ocr_factory import build_ocr_adapter
from app.services.pipeline import run_pipeline
from app.services.run_queue import claim_queued_run, fail_claimed_run
from app.settings import get_settings

settings = get_settings()
redis_url = settings.redis_url or "redis://localhost:6379/0"

celery_app = Celery(
    "vie",
    broker=redis_url,
    backend=redis_url,
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="vie.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="vie.extract_native_blocks")
def extract_native_blocks_task(run_id: str) -> dict:
    db = SessionLocal()
    try:
        return extract_native_blocks(db, run_id)
    finally:
        db.close()


@celery_app.task(bind=True, name="vie.run_pipeline")
def run_pipeline_task(task, run_id: str) -> dict:
    task_id = str(task.request.id or "")
    db = SessionLocal()
    try:
        claimed, status = claim_queued_run(db, run_id, task_id=task_id)
        if not claimed:
            return {"run_id": run_id, "status": status, "ignored": True}
        try:
            adapter = build_ocr_adapter(settings)
            return run_pipeline(
                db,
                run_id,
                ocr_adapter=adapter,
                ocr_min_confidence=settings.ocr_min_confidence,
            )
        except Exception as exc:
            fail_claimed_run(db, run_id, exc=exc)
            raise
    finally:
        db.close()
