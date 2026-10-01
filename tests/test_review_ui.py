from app.db import SessionLocal
from app.models import ReviewTask, VocabularyEntry
from app.services.extraction import extract_native_blocks
from app.services.segmentation import segment_source_entries
from app.services.structured_extraction import extract_canonical_fields


def test_review_ui_queue_detail_and_source_image(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("review-ui.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]
    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        segment_source_entries(db, run_id)
        extract_canonical_fields(db, run_id)
        entry = (
            db.query(VocabularyEntry)
            .filter(VocabularyEntry.processing_run_id == run_id)
            .one()
        )
        task = ReviewTask(
            processing_run_id=run_id,
            reason_code="MANUAL_QA",
            target_entity_type="VocabularyEntry",
            target_entity_id=entry.id,
            target_field_path="lemma",
            source_context={"note": "compare against source"},
            candidate_values=[entry.lemma],
        )
        db.add(task)
        db.commit()
        task_id = task.id
    finally:
        db.close()

    ui = client.get("/review")
    queue = client.get("/api/v1/reviews", params={"status": "OPEN"})
    detail = client.get(f"/api/v1/reviews/{task_id}")

    assert ui.status_code == 200
    assert "人工复核" in ui.text
    assert "标记为非文本噪声" in ui.text
    assert queue.status_code == 200
    assert queue.json()["count"] >= queue.json()["returned_count"]
    assert queue.json()["limit"] == 100
    assert queue.json()["offset"] == 0
    selected = next(item for item in queue.json()["items"] if item["id"] == task_id)
    assert selected["current_value"] == "abandon"
    assert selected["source_text"]
    assert selected["page"]["page_number"] == 1
    assert detail.json() == selected

    image = client.get(selected["page"]["image_url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")


def test_review_detail_rejects_unknown_task(client):
    response = client.get("/api/v1/reviews/missing")
    assert response.status_code == 404
