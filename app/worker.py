from __future__ import annotations

import os

from celery import Celery

from app.db import SessionLocal
from app.services.extraction import extract_native_blocks

celery_app = Celery(
    "vie",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
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
