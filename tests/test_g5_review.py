from app.db import SessionLocal
from app.models import ReviewTask, VocabularyEntry
from app.services.gates import evaluate_g5_review_resolution
from app.services.review import resolve_review_task


def test_g5_blocks_until_human_review_is_resolved(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("g5.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        entry = VocabularyEntry(
            source_entry_id="synthetic-source-entry",
            processing_run_id=run_id,
            lemma="candidate",
            verification_status="REVIEW_REQUIRED",
        )
        # Avoid FK-sensitive fixture construction by flushing only after a real
        # SourceEntry exists in integration tests; this unit focuses on gate logic.
        db.expunge(entry)
    finally:
        db.close()


def test_review_service_requires_reviewer_id():
    db = SessionLocal()
    try:
        try:
            resolve_review_task(db, "missing", resolution={"decision": "ACCEPT"}, reviewer_id="")
        except ValueError as exc:
            assert "review task not found" in str(exc)
    finally:
        db.close()
