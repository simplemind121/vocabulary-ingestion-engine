import json

from app.db import SessionLocal
from app.services.benchmark_artifact import persist_benchmark_report
from app.services.benchmark_run import build_run_prediction
from app.services.pipeline import run_pipeline
from app.storage import LocalStorageAdapter


def test_benchmark_report_is_persisted_as_immutable_sha256_artifact(
    client, sample_pdf_bytes, tmp_path
):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("benchmark-artifact.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        run_pipeline(db, run_id, publish=False)
        truth = build_run_prediction(db, run_id)
        storage = LocalStorageAdapter(tmp_path)
        artifact = persist_benchmark_report(
            db,
            run_id,
            truth,
            storage=storage,
        )
        first_id = artifact.id
        payload = storage.read_bytes(artifact.object_key)
        report = json.loads(payload)
        assert artifact.artifact_type == "BENCHMARK_REPORT_JSON"
        assert artifact.mime_type == "application/json"
        assert len(artifact.sha256) == 64
        assert report["processing_run_id"] == run_id
        assert report["status"] == "PASS"
        assert report["exact_match"] is True
        assert artifact.metadata_json["status"] == "PASS"

        repeated = persist_benchmark_report(
            db,
            run_id,
            truth,
            storage=storage,
        )
        assert repeated.id == first_id
        assert repeated.sha256 == artifact.sha256
    finally:
        db.close()
