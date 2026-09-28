from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated

import fitz
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import Base, engine, get_db
from app.models import (
    Artifact,
    Document,
    DocumentVersion,
    GateEvaluation,
    GoldRelease,
    Page,
    ProcessingRun,
    ReviewTask,
)
from app.services.gates import evaluate_g5_review_resolution
from app.services.gold import build_gold_dataset, publish_gold_release
from app.services.pipeline import run_pipeline
from app.services.review import resolve_review_task

APP_VERSION = "0.1.0-alpha.4"
DATA_DIR = Path("data")
BRONZE_DIR = DATA_DIR / "bronze"
PAGE_DIR = DATA_DIR / "pages"
BRONZE_DIR.mkdir(parents=True, exist_ok=True)
PAGE_DIR.mkdir(parents=True, exist_ok=True)
Base.metadata.create_all(bind=engine)
app = FastAPI(title="Vocabulary Ingestion Engine", version=APP_VERSION)
DbSession = Annotated[Session, Depends(get_db)]


class PublishRequest(BaseModel):
    unresolved_records: int = 0
    missing_required_provenance: int = 0
    open_required_reviews: int = 0
    blocking_validation_errors: int = 0


class ReviewResolutionRequest(BaseModel):
    reviewer_id: str
    decision: str = "ACCEPT"
    lemma: str | None = None
    notes: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@app.post("/api/v1/documents")
async def ingest_document(file: Annotated[UploadFile, File()], db: DbSession) -> dict:
    if file.content_type not in {"application/pdf", "application/x-pdf"}: raise HTTPException(415, "Only PDF is supported in v0.1")
    payload = await file.read()
    if not payload: raise HTTPException(400, "Empty upload")
    digest = hashlib.sha256(payload).hexdigest(); source_path = BRONZE_DIR / f"{digest}.pdf"; source_path.write_bytes(payload)
    try: pdf = fitz.open(stream=payload, filetype="pdf")
    except Exception as exc:
        source_path.unlink(missing_ok=True); raise HTTPException(422, f"Unreadable PDF: {exc}") from exc
    document = Document(original_filename=file.filename or "upload.pdf"); db.add(document); db.flush()
    source_artifact = Artifact(artifact_type="ORIGINAL_PDF", object_key=str(source_path), mime_type=file.content_type, byte_size=len(payload), sha256=digest); db.add(source_artifact); db.flush()
    version = DocumentVersion(document_id=document.id, source_artifact_id=source_artifact.id, sha256=digest, mime_type=file.content_type or "application/pdf", file_size=len(payload), page_count=pdf.page_count); db.add(version); db.flush()
    run = ProcessingRun(document_version_id=version.id, configuration_snapshot={"renderer": "pymupdf"}); db.add(run); db.flush()
    run_page_dir = PAGE_DIR / run.id; run_page_dir.mkdir(parents=True, exist_ok=True); rendered = []
    try:
        for index, page in enumerate(pdf):
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False); page_path = run_page_dir / f"page-{index + 1:04d}.png"; pix.save(page_path); page_bytes = page_path.read_bytes(); page_digest = hashlib.sha256(page_bytes).hexdigest()
            artifact = Artifact(artifact_type="PAGE_IMAGE", object_key=str(page_path), mime_type="image/png", byte_size=len(page_bytes), sha256=page_digest); db.add(artifact); db.flush()
            page_row = Page(document_version_id=version.id, page_number=index + 1, render_artifact_id=artifact.id); db.add(page_row); rendered.append({"page_number": index + 1, "artifact_id": artifact.id})
    finally: pdf.close()
    metrics = {"source_artifact_coverage": 1.0, "render_coverage": 1.0 if len(rendered) == version.page_count and rendered else 0.0, "missing_pages": max(version.page_count - len(rendered), 0)}; status = "PASS" if metrics["render_coverage"] == 1.0 else "FAIL"
    gate = GateEvaluation(processing_run_id=run.id, gate="G0", scope_type="DOCUMENT", scope_id=document.id, status=status, metrics=metrics, blocking_failures=[] if status == "PASS" else ["render_coverage"], evidence={"pdf_sha256": digest, "rendered_pages": len(rendered)}); db.add(gate)
    run.status = "READY" if status == "PASS" else "FAILED"; run.metrics = {"rendered_pages": len(rendered)}; db.commit()
    return {"id": document.id, "document_version_id": version.id, "filename": document.original_filename, "sha256": digest, "page_count": version.page_count, "run_id": run.id, "g0": {"gate": "G0", "status": status, "metrics": metrics}}


@app.get("/api/v1/documents/{document_id}")
def get_document(document_id: str, db: DbSession) -> dict:
    document = db.get(Document, document_id)
    if not document: raise HTTPException(404, "Document not found")
    return {"id": document.id, "filename": document.original_filename, "status": document.status}


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, db: DbSession) -> dict:
    run = db.get(ProcessingRun, run_id)
    if not run: raise HTTPException(404, "Processing run not found")
    gates = db.query(GateEvaluation).filter(GateEvaluation.processing_run_id == run_id).all()
    return {"id": run.id, "document_version_id": run.document_version_id, "status": run.status, "pipeline_version": run.pipeline_version, "error_summary": run.error_summary, "gates": [{"gate": g.gate, "status": g.status, "metrics": g.metrics} for g in gates]}


@app.post("/api/v1/runs/{run_id}/execute")
def execute_run(run_id: str, db: DbSession) -> dict:
    try: return run_pipeline(db, run_id)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc


@app.get("/api/v1/runs/{run_id}/reviews")
def list_reviews(run_id: str, db: DbSession, status: str | None = None) -> dict:
    run = db.get(ProcessingRun, run_id)
    if not run: raise HTTPException(404, "Processing run not found")
    query = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id)
    if status: query = query.filter(ReviewTask.status == status.upper())
    tasks = query.order_by(ReviewTask.created_at, ReviewTask.id).all()
    return {"run_id": run_id, "count": len(tasks), "items": [{"id": t.id, "status": t.status, "reason_code": t.reason_code, "target_entity_type": t.target_entity_type, "target_entity_id": t.target_entity_id, "target_field_path": t.target_field_path, "source_context": t.source_context, "candidate_values": t.candidate_values} for t in tasks]}


@app.post("/api/v1/reviews/{task_id}/resolve")
def resolve_review(task_id: str, request: ReviewResolutionRequest, db: DbSession) -> dict:
    resolution = {"decision": request.decision, "notes": request.notes}
    if request.lemma is not None: resolution["lemma"] = request.lemma
    try:
        result = resolve_review_task(db, task_id, resolution=resolution, reviewer_id=request.reviewer_id)
        result["g5"] = evaluate_g5_review_resolution(db, result["run_id"])
        return result
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(404 if "not found" in message else 409, message) from exc


@app.get("/api/v1/runs/{run_id}/gold")
def get_gold(run_id: str, db: DbSession) -> dict:
    try: return build_gold_dataset(db, run_id)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@app.post("/api/v1/runs/{run_id}/gold/publish")
def publish_gold(run_id: str, db: DbSession) -> dict:
    try: release = publish_gold_release(db, run_id)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    return {"release_id": release.id, "version": release.version, "sha256": release.sha256, "record_count": release.record_count, "json_artifact_id": release.json_artifact_id, "csv_artifact_id": release.csv_artifact_id}


@app.get("/api/v1/gold/releases/{release_id}")
def get_gold_release(release_id: str, db: DbSession) -> dict:
    release = db.get(GoldRelease, release_id)
    if not release: raise HTTPException(404, "Gold release not found")
    return {"release_id": release.id, "processing_run_id": release.processing_run_id, "version": release.version, "schema_version": release.schema_version, "record_count": release.record_count, "sha256": release.sha256, "json_artifact_id": release.json_artifact_id, "csv_artifact_id": release.csv_artifact_id}


@app.post("/api/v1/gold/preflight")
def gold_preflight(request: PublishRequest) -> dict:
    metrics = request.model_dump(); failures = [name for name, value in metrics.items() if value != 0]
    return {"gate": "G6", "status": "PASS" if not failures else "FAIL", "blocking_failures": failures, "metrics": metrics, "publish_allowed": not failures}
