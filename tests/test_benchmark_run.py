from app.db import SessionLocal
from app.services.benchmark_run import benchmark_processing_run
from app.services.pipeline import run_pipeline


def test_persisted_processing_run_can_be_benchmarked(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("benchmark-run.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        result = run_pipeline(db, run_id, publish=False)
        assert result["status"] in {"COMPLETED", "REVIEW_REQUIRED", "FAILED"}

        from app.services.benchmark_run import build_run_prediction

        prediction = build_run_prediction(db, run_id)
        benchmark = benchmark_processing_run(db, run_id, prediction)
        assert benchmark["processing_run_id"] == run_id
        assert benchmark["status"] == "PASS"
        assert benchmark["layers"]["ocr"]["exact_match"] is True
        assert benchmark["layers"]["segmentation"]["exact_match"] is True
        assert benchmark["layers"]["canonical"]["exact_match"] is True
    finally:
        db.close()
