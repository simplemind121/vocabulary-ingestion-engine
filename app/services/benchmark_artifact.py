from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import Artifact
from app.services.benchmark_run import benchmark_processing_run
from app.storage import LocalStorageAdapter, StorageAdapter


def serialize_benchmark_report(report: dict[str, Any]) -> bytes:
    return json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def persist_benchmark_report(
    db: Session,
    run_id: str,
    ground_truth: dict[str, Any],
    *,
    storage: StorageAdapter | None = None,
) -> Artifact:
    storage = storage or LocalStorageAdapter("data")
    report = benchmark_processing_run(db, run_id, ground_truth)
    payload = serialize_benchmark_report(report)
    digest = hashlib.sha256(payload).hexdigest()
    key = f"benchmarks/{run_id}/{digest}.json"

    existing = db.query(Artifact).filter(Artifact.object_key == key).one_or_none()
    if existing is not None:
        if existing.sha256 != digest:
            raise ValueError(f"immutable artifact collision at {key}")
        return existing

    stored = storage.put_bytes(key, payload)
    artifact = Artifact(
        artifact_type="BENCHMARK_REPORT_JSON",
        storage_provider=stored["provider"],
        bucket="local",
        object_key=stored["object_key"],
        mime_type="application/json",
        byte_size=stored["byte_size"],
        sha256=stored["sha256"],
        metadata_json={
            "immutable": True,
            "processing_run_id": run_id,
            "benchmark_schema_version": report["benchmark_schema_version"],
            "status": report["status"],
            "exact_match": report["exact_match"],
        },
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact
