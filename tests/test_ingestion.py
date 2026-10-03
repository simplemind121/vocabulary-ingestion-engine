import fitz
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import BRONZE_DIR, app
from app.models import Artifact, DocumentVersion, ProcessingRun
from app.services.gold_page_hashes import GOLD_RENDER_CONTRACT
from app.settings import get_settings

client = TestClient(app)


def make_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "abandon /əˈbændən/ v. to leave")
    payload = doc.tobytes()
    doc.close()
    return payload


def test_pdf_ingestion_persists_document_run_and_g0():
    response = client.post(
        "/api/v1/documents",
        files={"file": ("sample.pdf", make_pdf(), "application/pdf")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["page_count"] == 1
    assert body["g0"]["status"] == "PASS"

    document = client.get(f"/api/v1/documents/{body['id']}")
    assert document.status_code == 200
    assert document.json()["filename"] == "sample.pdf"

    run = client.get(f"/api/v1/runs/{body['run_id']}")
    assert run.status_code == 200
    assert run.json()["status"] == "READY"
    assert run.json()["gates"][0]["gate"] == "G0"

    db = SessionLocal()
    try:
        persisted_run = db.get(ProcessingRun, body["run_id"])
        assert persisted_run.configuration_snapshot["render_contract"] == GOLD_RENDER_CONTRACT
    finally:
        db.close()


def test_identical_uploads_reuse_the_content_addressed_source_artifact():
    payload = make_pdf()
    first = client.post(
        "/api/v1/documents",
        files={"file": ("first.pdf", payload, "application/pdf")},
    )
    second = client.post(
        "/api/v1/documents",
        files={"file": ("second.pdf", payload, "application/pdf")},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]

    db = SessionLocal()
    try:
        first_version = db.get(DocumentVersion, first.json()["document_version_id"])
        second_version = db.get(DocumentVersion, second.json()["document_version_id"])
        assert first_version is not None
        assert second_version is not None
        assert first_version.source_artifact_id == second_version.source_artifact_id
        source_artifacts = (
            db.query(Artifact)
            .filter(
                Artifact.artifact_type == "ORIGINAL_PDF",
                Artifact.sha256 == first.json()["sha256"],
            )
            .all()
        )
        assert len(source_artifacts) == 1
    finally:
        db.close()


def test_upload_limit_rejects_pdf_without_ingesting(monkeypatch):
    monkeypatch.setenv("VIE_MAX_UPLOAD_BYTES", "32")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("too-large.pdf", make_pdf(), "application/pdf")},
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 413
    assert "32-byte upload limit" in response.json()["detail"]


def test_page_limit_rejects_pdf_before_rendering(monkeypatch):
    monkeypatch.setenv("VIE_MAX_PDF_PAGES", "1")
    get_settings.cache_clear()
    document = fitz.open()
    document.new_page()
    document.new_page()
    payload = document.tobytes()
    document.close()
    try:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("too-many-pages.pdf", payload, "application/pdf")},
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 422
    assert "1-page limit" in response.json()["detail"]


def test_render_budget_rejects_oversized_page(monkeypatch):
    monkeypatch.setenv("VIE_MAX_RENDER_PIXELS_PER_PAGE", "1000")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("oversized-page.pdf", make_pdf(), "application/pdf")},
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 422
    assert "1000-pixel render limit" in response.json()["detail"]


def test_invalid_pdf_is_rejected_and_staging_file_is_removed():
    before = set(BRONZE_DIR.glob(".upload-*.pdf"))

    response = client.post(
        "/api/v1/documents",
        files={"file": ("invalid.pdf", b"not a PDF", "application/pdf")},
    )

    assert response.status_code == 422
    assert "Unreadable PDF" in response.json()["detail"]
    assert set(BRONZE_DIR.glob(".upload-*.pdf")) == before


def test_empty_and_wrong_media_type_uploads_are_rejected():
    empty = client.post(
        "/api/v1/documents",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    wrong_type = client.post(
        "/api/v1/documents",
        files={"file": ("source.txt", b"text", "text/plain")},
    )

    assert empty.status_code == 400
    assert wrong_type.status_code == 415
