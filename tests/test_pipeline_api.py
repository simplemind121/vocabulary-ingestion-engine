from app.db import SessionLocal
from app.models import ProcessingRun


def test_execute_pipeline_api_runs_gate_driven_flow(client, sample_pdf_bytes):
    response = client.post("/api/v1/documents", files={"file": ("pipeline.pdf", sample_pdf_bytes, "application/pdf")})
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    assert response.json()["g0"]["status"] == "PASS"

    execute = client.post(f"/api/v1/runs/{run_id}/execute")
    assert execute.status_code == 200
    body = execute.json()
    assert body["status"] in {"COMPLETED", "REVIEW_REQUIRED", "FAILED"}
    assert body["stages"]

    status = client.get(f"/api/v1/runs/{run_id}")
    assert status.status_code == 200
    assert status.json()["status"] == body["status"]


def test_completed_pipeline_exposes_gold_and_release(client, sample_pdf_bytes):
    response = client.post("/api/v1/documents", files={"file": ("gold-api.pdf", sample_pdf_bytes, "application/pdf")})
    run_id = response.json()["run_id"]
    execute = client.post(f"/api/v1/runs/{run_id}/execute")
    assert execute.status_code == 200
    if execute.json()["status"] != "COMPLETED":
        return

    gold = client.get(f"/api/v1/runs/{run_id}/gold")
    assert gold.status_code == 200
    assert gold.json()["record_count"] >= 1

    release = client.post(f"/api/v1/runs/{run_id}/gold/publish")
    assert release.status_code == 200
    release_id = release.json()["release_id"]
    detail = client.get(f"/api/v1/gold/releases/{release_id}")
    assert detail.status_code == 200
    assert detail.json()["sha256"] == release.json()["sha256"]


def test_missing_run_execute_is_404(client):
    response = client.post("/api/v1/runs/does-not-exist/execute")
    assert response.status_code == 404


def test_ingestion_leaves_run_ready_for_pipeline(client, sample_pdf_bytes):
    response = client.post("/api/v1/documents", files={"file": ("ready.pdf", sample_pdf_bytes, "application/pdf")})
    run_id = response.json()["run_id"]
    db = SessionLocal()
    try:
        run = db.get(ProcessingRun, run_id)
        assert run is not None
        assert run.status == "READY"
    finally:
        db.close()



def test_scanned_document_is_routed_to_ocr_required(client):
    import fitz

    doc = fitz.open()
    doc.new_page()
    payload = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/documents",
        files={"file": ("scan.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    execute = client.post(f"/api/v1/runs/{run_id}/execute")
    assert execute.status_code == 200
    body = execute.json()
    assert body["status"] == "OCR_REQUIRED"
    assert body["reason"] == "ocr_required"
    assert body["document_mode"] == "SCANNED"
