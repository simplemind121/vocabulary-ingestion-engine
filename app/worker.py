from __future__ import annotations

from celery import Celery

from app.db import SessionLocal
from app.services.extraction import extract_native_blocks
from app.settings import get_settings

settings = get_settings()
redis_url = settings.redis_url or "redis://localhost:6379/0"

celery_app = Celery(
    "vie",
    broker=redis_url,
    backend=redis_url,
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
