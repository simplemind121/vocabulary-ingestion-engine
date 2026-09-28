from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import fitz
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

APP_VERSION = "0.1.0-alpha.1"
DATA_DIR = Path("data")
BRONZE_DIR = DATA_DIR / "bronze"
PAGE_DIR = DATA_DIR / "pages"
BRONZE_DIR.mkdir(parents=True, exist_ok=True)
PAGE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Vocabulary Ingestion Engine", version=APP_VERSION)

# Bootstrap persistence only. PostgreSQL repository replaces this store in M0.2.
DOCUMENTS: dict[str, dict] = {}
RUNS: dict[str, dict] = {}


class PublishRequest(BaseModel):
    unresolved_records: int = 0
    missing_required_provenance: int = 0
    open_required_reviews: int = 0
    blocking_validation_errors: int = 0


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@app.post("/api/v1/documents")
async def ingest_document(file: UploadFile = File(...)) -> dict:
    if file.content_type not in {"application/pdf", "application/x-pdf"}:
        raise HTTPException(415, "Only PDF is supported in v0.1")
    payload = await file.read()
    if not payload:
        raise HTTPException(400, "Empty upload")

    digest = hashlib.sha256(payload).hexdigest()
    document_id = str(uuid.uuid4())
    source_path = BRONZE_DIR / f"{digest}.pdf"
    source_path.write_bytes(payload)

    try:
        pdf = fitz.open(stream=payload, filetype="pdf")
    except Exception as exc:
        source_path.unlink(missing_ok=True)
        raise HTTPException(422, f"Unreadable PDF: {exc}") from exc

    run_id = str(uuid.uuid4())
    rendered = []
    run_page_dir = PAGE_DIR / run_id
    run_page_dir.mkdir(parents=True, exist_ok=True)
    try:
        for index, page in enumerate(pdf):
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            page_path = run_page_dir / f"page-{index + 1:04d}.png"
            pix.save(page_path)
            rendered.append({"page_number": index + 1, "path": str(page_path)})
    finally:
        pdf.close()

    gate_g0 = {
        "gate": "G0",
        "status": "PASS" if rendered else "FAIL",
        "metrics": {
            "source_artifact_coverage": 1.0,
            "render_coverage": 1.0 if rendered else 0.0,
            "missing_pages": 0,
        },
    }
    document = {
        "id": document_id,
        "filename": file.filename,
        "sha256": digest,
        "source_path": str(source_path),
        "page_count": len(rendered),
        "run_id": run_id,
        "g0": gate_g0,
    }
    DOCUMENTS[document_id] = document
    RUNS[run_id] = {"id": run_id, "document_id": document_id, "pages": rendered, "g0": gate_g0}
    return document


@app.get("/api/v1/documents/{document_id}")
def get_document(document_id: str) -> dict:
    document = DOCUMENTS.get(document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    return document


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "Processing run not found")
    return run


@app.post("/api/v1/gold/preflight")
def gold_preflight(request: PublishRequest) -> dict:
    metrics = request.model_dump()
    failures = [name for name, value in metrics.items() if value != 0]
    return {
        "gate": "G6",
        "status": "PASS" if not failures else "FAIL",
        "blocking_failures": failures,
        "metrics": metrics,
        "publish_allowed": not failures,
    }
