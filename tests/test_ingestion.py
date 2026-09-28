import fitz
from fastapi.testclient import TestClient

from app.main import app

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
