from app import main
from app.db import SessionLocal
from app.models import ProcessingRun
from app.services.run_queue import claim_queued_run, queue_processing_run


def test_enqueue_api_records_task_and_rejects_duplicate(
    client, sample_pdf_bytes, monkeypatch
):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("queued.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]
    dispatched = []

    def fake_apply_async(*, args, task_id):
        dispatched.append((args, task_id))

    monkeypatch.setattr(main.run_pipeline_task, "apply_async", fake_apply_async)

    queued = client.post(f"/api/v1/runs/{run_id}/enqueue")
    duplicate = client.post(f"/api/v1/runs/{run_id}/enqueue")
    status = client.get(f"/api/v1/runs/{run_id}")

    assert queued.status_code == 202
    assert queued.json()["status"] == "QUEUED"
    assert dispatched == [([run_id], queued.json()["task_id"])]
    assert duplicate.status_code == 409
    assert status.json()["status"] == "QUEUED"
    assert status.json()["metrics"]["queue_task_id"] == queued.json()["task_id"]
    assert client.post(f"/api/v1/runs/{run_id}/execute").status_code == 409


def test_enqueue_api_records_dispatch_failure(client, sample_pdf_bytes, monkeypatch):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("queue-failure.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    def fail_dispatch(**kwargs):
        del kwargs
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(main.run_pipeline_task, "apply_async", fail_dispatch)

    failed = client.post(f"/api/v1/runs/{run_id}/enqueue")
    status = client.get(f"/api/v1/runs/{run_id}").json()

    assert failed.status_code == 503
    assert status["status"] == "QUEUE_FAILED"
    assert status["error_summary"]["stage"] == "queue_dispatch"


def test_worker_claim_is_bound_to_the_exact_queued_task(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("claim.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]
    db = SessionLocal()
    try:
        queued = queue_processing_run(db, run_id, dispatch=lambda run_id, task_id: None)
        wrong = claim_queued_run(db, run_id, task_id="wrong-task")
        claimed = claim_queued_run(db, run_id, task_id=queued["task_id"])
        duplicate = claim_queued_run(db, run_id, task_id=queued["task_id"])
        run = db.get(ProcessingRun, run_id)
    finally:
        db.close()

    assert wrong == (False, "QUEUED")
    assert claimed == (True, "STARTING")
    assert duplicate == (False, "STARTING")
    assert run is not None
    assert run.status == "STARTING"
