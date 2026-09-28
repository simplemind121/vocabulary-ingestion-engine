from __future__ import annotations

import os

from celery import Celery

celery_app = Celery(
    "vie",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)


@celery_app.task(name="vie.ping")
def ping() -> str:
    return "pong"
