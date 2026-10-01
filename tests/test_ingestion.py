import fitz
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Artifact, DocumentVersion, ProcessingRun
from app.services.gold_page_hashes import GOLD_RENDER_CONTRACT

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
