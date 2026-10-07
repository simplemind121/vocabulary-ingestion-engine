from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import secrets
import tempfile
import time
import uuid
from pathlib import Path
from typing import Annotated

import fitz
import redis
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.console_ui import CONSOLE_UI_HTML
from app.db import get_db
from app.models import (
    Artifact,
    Document,
    DocumentVersion,
    GateEvaluation,
    GoldRelease,
    Page,
    ProcessingRun,
    ReviewTask,
    SourceMedia,
)
from app.observability import PROMETHEUS_CONTENT_TYPE, log_event, render_metrics
from app.review_ui import REVIEW_UI_HTML
from app.services.gates import evaluate_g5_review_resolution
from app.services.gold import build_gold_dataset, build_preview_dataset, publish_gold_release
from app.services.gold_page_hashes import GOLD_RENDER_CONTRACT
from app.services.ocr_factory import build_ocr_adapter
from app.services.pipeline import run_pipeline
from app.services.review import resolve_review_task
from app.services.review_view import review_task_detail
from app.services.run_queue import queue_processing_run
from app.services.source_media import serialize_source_media, source_media_metrics
from app.settings import Settings, get_settings
from app.storage import build_storage_adapter, read_artifact_bytes
from app.worker import run_pipeline_task

APP_VERSION = "0.1.0-alpha.4"
DATA_DIR = Path("data")
BRONZE_DIR = DATA_DIR / "bronze"
PAGE_DIR = DATA_DIR / "pages"
BRONZE_DIR.mkdir(parents=True, exist_ok=True)
PAGE_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="Vocabulary Ingestion Engine", version=APP_VERSION)
DbSession = Annotated[Session, Depends(get_db)]
logger = logging.getLogger("uvicorn.error")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    expected_secret = get_settings().api_key
    protected = request.url.path.startswith("/api/") or request.url.path == "/metrics"
    if protected and expected_secret is not None:
        authorization = request.headers.get("authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        expected = expected_secret.get_secret_value()
        if scheme.lower() != "bearer" or not supplied or not secrets.compare_digest(supplied, expected):
            return JSONResponse(
                status_code=401,
                content={"detail": "Valid bearer token required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)


@app.middleware("http")
async def observe_request(request: Request, call_next):
    supplied_request_id = request.headers.get("x-request-id", "")
    request_id = (
        supplied_request_id
        if _REQUEST_ID.fullmatch(supplied_request_id)
        else str(uuid.uuid4())
    )
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        log_event(
            logger,
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )


class PublishRequest(BaseModel):
    unresolved_records: int = 0
    missing_required_provenance: int = 0
    open_required_reviews: int = 0
    blocking_validation_errors: int = 0


class ReviewResolutionRequest(BaseModel):
    reviewer_id: str
    decision: str = "ACCEPT"
    lemma: str | None = None
    corrected_text: str | None = None
    classification: str | None = None
    source_entry_id: str | None = None
    notes: str | None = None


def _get_or_create_source_artifact(
    db: Session,
    *,
    source_path: Path,
    content_type: str | None,
    byte_size: int,
    digest: str,
) -> Artifact:
    object_key = str(source_path)
    existing = db.query(Artifact).filter(Artifact.object_key == object_key).one_or_none()
    if existing is not None:
        if existing.artifact_type != "ORIGINAL_PDF" or existing.sha256 != digest:
            raise RuntimeError(f"source artifact identity conflict: {object_key}")
        return existing

    candidate = Artifact(
        artifact_type="ORIGINAL_PDF",
        object_key=object_key,
        mime_type=content_type,
        byte_size=byte_size,
        sha256=digest,
    )
    try:
        # The savepoint keeps concurrent, identical uploads from invalidating the
        # outer document transaction when the unique object key wins elsewhere.
        with db.begin_nested():
            db.add(candidate)
            db.flush()
        return candidate
    except IntegrityError:
        existing = db.query(Artifact).filter(Artifact.object_key == object_key).one_or_none()
        if (
            existing is None
            or existing.artifact_type != "ORIGINAL_PDF"
            or existing.sha256 != digest
        ):
            raise
        return existing


async def _stage_pdf_upload(file: UploadFile) -> tuple[Path, str, int]:
    settings = get_settings()
    digest = hashlib.sha256()
    byte_size = 0
    staged_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=BRONZE_DIR,
            prefix=".upload-",
            suffix=".pdf",
            delete=False,
        ) as staged:
            staged_path = Path(staged.name)
            while chunk := await file.read(1024 * 1024):
                byte_size += len(chunk)
                if byte_size > settings.max_upload_bytes:
                    raise HTTPException(
                        413,
                        f"PDF exceeds configured {settings.max_upload_bytes}-byte upload limit",
                    )
                digest.update(chunk)
                staged.write(chunk)
        if byte_size == 0:
            raise HTTPException(400, "Empty upload")
        _validate_pdf_policy(staged_path, settings=settings)

        sha256 = digest.hexdigest()
        source_path = BRONZE_DIR / f"{sha256}.pdf"
        if source_path.exists() and _sha256_file(source_path) == sha256:
            staged_path.unlink()
        else:
            os.replace(staged_path, source_path)
        staged_path = None
        return source_path, sha256, byte_size
    finally:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)


def _validate_pdf_policy(path: Path, *, settings: Settings) -> None:
    try:
        pdf = fitz.open(path)
    except Exception as exc:
        raise HTTPException(422, f"Unreadable PDF: {exc}") from exc
    try:
        if pdf.needs_pass:
            raise HTTPException(422, "Encrypted PDFs are not supported")
        if pdf.page_count == 0:
            raise HTTPException(422, "PDF contains no pages")
        if pdf.page_count > settings.max_pdf_pages:
            raise HTTPException(
                422,
                f"PDF exceeds configured {settings.max_pdf_pages}-page limit",
            )
        scale_x, scale_y = GOLD_RENDER_CONTRACT["matrix"]
        for page_number, page in enumerate(pdf, start=1):
            width = page.rect.width * scale_x
            height = page.rect.height * scale_y
            pixels = width * height
            if not math.isfinite(pixels) or pixels > settings.max_render_pixels_per_page:
                raise HTTPException(
                    422,
                    "PDF page "
                    f"{page_number} exceeds configured "
                    f"{settings.max_render_pixels_per_page}-pixel render limit",
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"PDF validation failed: {exc}") from exc
    finally:
        pdf.close()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/health/live")
def health_live() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/health/ready")
def health_ready(db: DbSession) -> Response:
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except SQLAlchemyError:
        checks["database"] = "unavailable"

    settings = get_settings()
    if settings.redis_url:
        try:
            redis.Redis.from_url(settings.redis_url, socket_timeout=1).ping()
            checks["redis"] = "ok"
        except redis.RedisError:
            checks["redis"] = "unavailable"
    else:
        checks["redis"] = "not_configured"

    try:
        build_storage_adapter(settings).healthcheck()
        checks["storage"] = "ok"
    except (BotoCoreError, ClientError, OSError, ValueError):
        checks["storage"] = "unavailable"

    ready = all(value != "unavailable" for value in checks.values())
    return Response(
        content=json.dumps({"status": "ready" if ready else "not_ready", "checks": checks}),
        media_type="application/json",
        status_code=200 if ready else 503,
    )


@app.get("/metrics", include_in_schema=False)
def metrics(db: DbSession) -> Response:
    return Response(
        content=render_metrics(db, version=APP_VERSION),
        media_type=PROMETHEUS_CONTENT_TYPE,
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def console_ui() -> str:
    return CONSOLE_UI_HTML


@app.get("/review", response_class=HTMLResponse, include_in_schema=False)
def review_ui() -> str:
    return REVIEW_UI_HTML


@app.post("/api/v1/documents")
async def ingest_document(file: Annotated[UploadFile, File()], db: DbSession) -> dict:
    if file.content_type not in {"application/pdf", "application/x-pdf"}: raise HTTPException(415, "Only PDF is supported in v0.1")
    source_path, digest, byte_size = await _stage_pdf_upload(file)
    pdf = fitz.open(source_path)
    document = Document(original_filename=file.filename or "upload.pdf"); db.add(document); db.flush()
    source_artifact = _get_or_create_source_artifact(
        db,
        source_path=source_path,
        content_type=file.content_type,
        byte_size=byte_size,
        digest=digest,
    )
    version = DocumentVersion(document_id=document.id, source_artifact_id=source_artifact.id, sha256=digest, mime_type=file.content_type or "application/pdf", file_size=byte_size, page_count=pdf.page_count); db.add(version); db.flush()
    run = ProcessingRun(
        document_version_id=version.id,
        configuration_snapshot={"render_contract": GOLD_RENDER_CONTRACT},
    ); db.add(run); db.flush()
    run_page_dir = PAGE_DIR / run.id; run_page_dir.mkdir(parents=True, exist_ok=True); rendered = []
    try:
        for index, page in enumerate(pdf):
            matrix = GOLD_RENDER_CONTRACT["matrix"]
            pix = page.get_pixmap(matrix=fitz.Matrix(*matrix), alpha=False); page_path = run_page_dir / f"page-{index + 1:04d}.png"; pix.save(page_path); page_bytes = page_path.read_bytes(); page_digest = hashlib.sha256(page_bytes).hexdigest()
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


@app.get("/api/v1/runs")
def list_runs(db: DbSession, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
    """Newest runs first, with what the console needs to list them."""
    rows = (
        db.query(ProcessingRun, DocumentVersion, Document)
        .join(DocumentVersion, DocumentVersion.id == ProcessingRun.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .order_by(ProcessingRun.created_at.desc())
        .limit(limit)
        .all()
    )
    open_reviews = dict(
        db.query(ReviewTask.processing_run_id, func.count())
        .filter(ReviewTask.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"]))
        .group_by(ReviewTask.processing_run_id)
        .all()
    )
    return {
        "items": [
            {
                "id": run.id,
                "status": run.status,
                "filename": document.original_filename,
                "sha256": version.sha256,
                "page_count": version.page_count,
                "created_at": run.created_at,
                "open_reviews": open_reviews.get(run.id, 0),
                "gold_release_id": (run.metrics or {}).get("gold_release_id"),
            }
            for run, version, document in rows
        ]
    }


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, db: DbSession) -> dict:
    run = db.get(ProcessingRun, run_id)
    if not run: raise HTTPException(404, "Processing run not found")
    gates = db.query(GateEvaluation).filter(GateEvaluation.processing_run_id == run_id).all()
    return {"id": run.id, "document_version_id": run.document_version_id, "status": run.status, "pipeline_version": run.pipeline_version, "metrics": run.metrics, "error_summary": run.error_summary, "started_at": run.started_at, "finished_at": run.finished_at, "gates": [{"gate": g.gate, "status": g.status, "metrics": g.metrics} for g in gates]}


@app.post("/api/v1/runs/{run_id}/enqueue", status_code=202)
def enqueue_run(run_id: str, db: DbSession) -> dict:
    try:
        return queue_processing_run(
            db,
            run_id,
            dispatch=lambda queued_run_id, task_id: run_pipeline_task.apply_async(
                args=[queued_run_id], task_id=task_id
            ),
        )
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(404 if "not found" in message else 409, message) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/v1/runs/{run_id}/execute")
def execute_run(run_id: str, db: DbSession) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise HTTPException(404, "processing run not found")
    if run.status in {"QUEUED", "STARTING", "RUNNING"}:
        raise HTTPException(409, f"processing run is already active: {run.status}")
    try:
        settings = get_settings()
        adapter = build_ocr_adapter(settings)
        return run_pipeline(
            db,
            run_id,
            ocr_adapter=adapter,
            ocr_min_confidence=settings.ocr_min_confidence,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/v1/runs/{run_id}/reviews")
def list_reviews(run_id: str, db: DbSession, status: str | None = None) -> dict:
    run = db.get(ProcessingRun, run_id)
    if not run: raise HTTPException(404, "Processing run not found")
    query = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id)
    if status: query = query.filter(ReviewTask.status == status.upper())
    tasks = query.order_by(ReviewTask.created_at, ReviewTask.id).all()
    return {
        "run_id": run_id,
        "count": len(tasks),
        "items": [review_task_detail(db, task) for task in tasks],
    }


@app.get("/api/v1/reviews")
def list_all_reviews(
    db: DbSession,
    status: str | None = "OPEN",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    query = db.query(ReviewTask)
    if status:
        query = query.filter(ReviewTask.status == status.upper())
    count = query.count()
    tasks = (
        query.order_by(ReviewTask.created_at.desc(), ReviewTask.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "count": count,
        "returned_count": len(tasks),
        "limit": limit,
        "offset": offset,
        "items": [review_task_detail(db, task) for task in tasks],
    }


@app.get("/api/v1/reviews/{task_id}")
def get_review(task_id: str, db: DbSession) -> dict:
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise HTTPException(404, "Review task not found")
    return review_task_detail(db, task)


@app.get("/api/v1/pages/{page_id}/image")
def get_page_image(page_id: str, db: DbSession) -> Response:
    page = db.get(Page, page_id)
    if page is None:
        raise HTTPException(404, "Page not found")
    artifact = db.get(Artifact, page.render_artifact_id)
    if artifact is None:
        raise HTTPException(404, "Page image artifact not found")
    try:
        payload = read_artifact_bytes(
            storage_provider=artifact.storage_provider,
            object_key=artifact.object_key,
            settings=get_settings(),
        )
    except (BotoCoreError, ClientError, OSError, ValueError) as exc:
        raise HTTPException(503, "Page image storage unavailable") from exc
    return Response(
        content=payload,
        media_type=artifact.mime_type or "image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.get("/api/v1/runs/{run_id}/source-media")
def list_source_media(run_id: str, db: DbSession) -> dict:
    if db.get(ProcessingRun, run_id) is None:
        raise HTTPException(404, "Run not found")
    rows = (
        db.query(SourceMedia)
        .filter(SourceMedia.processing_run_id == run_id)
        .order_by(SourceMedia.page_number, SourceMedia.media_order)
        .all()
    )
    return {
        "run_id": run_id,
        "namespace": "SOURCE_MEDIA",
        "metrics": source_media_metrics(db, run_id, verify_bytes=False),
        "items": [
            {
                **serialize_source_media(db, row),
                "vocabulary_entry_id": row.vocabulary_entry_id,
                "content_url": f"/api/v1/source-media/{row.id}/content",
            }
            for row in rows
        ],
    }


@app.get("/api/v1/source-media/{media_id}/content")
def get_source_media_content(media_id: str, db: DbSession) -> Response:
    media = db.get(SourceMedia, media_id)
    if media is None:
        raise HTTPException(404, "Source media not found")
    artifact = db.get(Artifact, media.artifact_id)
    if artifact is None:
        raise HTTPException(404, "Source media artifact not found")
    try:
        payload = read_artifact_bytes(
            storage_provider=artifact.storage_provider,
            object_key=artifact.object_key,
            settings=get_settings(),
        )
    except (BotoCoreError, ClientError, OSError, ValueError) as exc:
        raise HTTPException(503, "Source media storage unavailable") from exc
    return Response(
        content=payload,
        media_type=media.mime_type,
        headers={"Cache-Control": "private, max-age=300", "X-Content-SHA256": media.sha256},
    )


@app.post("/api/v1/reviews/{task_id}/resolve")
def resolve_review(task_id: str, request: ReviewResolutionRequest, db: DbSession) -> dict:
    resolution = {"decision": request.decision, "notes": request.notes}
    if request.lemma is not None: resolution["lemma"] = request.lemma
    if request.corrected_text is not None: resolution["corrected_text"] = request.corrected_text
    if request.classification is not None: resolution["classification"] = request.classification
    if request.source_entry_id is not None: resolution["source_entry_id"] = request.source_entry_id
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


@app.get("/api/v1/runs/{run_id}/preview")
def get_preview(run_id: str, db: DbSession) -> dict:
    """Entries as they stand, including ones still awaiting confirmation."""
    try: return build_preview_dataset(db, run_id)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@app.post("/api/v1/runs/{run_id}/gold/publish")
def publish_gold(run_id: str, db: DbSession) -> dict:
    try: release = publish_gold_release(db, run_id)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    return {"release_id": release.id, "version": release.version, "sha256": release.sha256, "record_count": release.record_count, "json_artifact_id": release.json_artifact_id, "csv_artifact_id": release.csv_artifact_id, "xlsx_artifact_id": release.xlsx_artifact_id}


@app.get("/api/v1/gold/releases/{release_id}")
def get_gold_release(release_id: str, db: DbSession) -> dict:
    release = db.get(GoldRelease, release_id)
    if not release: raise HTTPException(404, "Gold release not found")
    return {"release_id": release.id, "processing_run_id": release.processing_run_id, "version": release.version, "schema_version": release.schema_version, "record_count": release.record_count, "sha256": release.sha256, "json_artifact_id": release.json_artifact_id, "csv_artifact_id": release.csv_artifact_id, "xlsx_artifact_id": release.xlsx_artifact_id}


@app.get("/api/v1/gold/releases/{release_id}/download/{artifact_format}")
def download_gold_release(release_id: str, artifact_format: str, db: DbSession) -> Response:
    release = db.get(GoldRelease, release_id)
    if not release:
        raise HTTPException(404, "Gold release not found")
    formats = {
        "json": (release.json_artifact_id, "application/json"),
        "csv": (release.csv_artifact_id, "text/csv; charset=utf-8"),
        "xlsx": (
            release.xlsx_artifact_id,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    }
    selected = formats.get(artifact_format.lower())
    if selected is None:
        raise HTTPException(404, "Gold artifact format not found")
    artifact = db.get(Artifact, selected[0]) if selected[0] else None
    if artifact is None:
        raise HTTPException(404, "Gold artifact not found")
    try:
        payload = read_artifact_bytes(
            storage_provider=artifact.storage_provider,
            object_key=artifact.object_key,
            settings=get_settings(),
        )
    except (BotoCoreError, ClientError, OSError, ValueError) as exc:
        raise HTTPException(503, "Gold artifact storage unavailable") from exc
    return Response(
        content=payload,
        media_type=selected[1],
        headers={"Content-Disposition": f'attachment; filename="gold-v{release.version:04d}.{artifact_format.lower()}"'},
    )


@app.post("/api/v1/gold/preflight")
def gold_preflight(request: PublishRequest) -> dict:
    metrics = request.model_dump(); failures = [name for name, value in metrics.items() if value != 0]
    return {"gate": "G6", "status": "PASS" if not failures else "FAIL", "blocking_failures": failures, "metrics": metrics, "publish_allowed": not failures}
