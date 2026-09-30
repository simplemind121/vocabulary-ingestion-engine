from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from app.gold_review_ui import GOLD_REVIEW_UI_HTML
from app.services.gold_review_session import GoldReviewSession


class VerifyGoldPageRequest(BaseModel):
    reviewer_id: str
    checks: list[str]
    records: list[dict[str, Any]] = Field(default_factory=list)
    page_classification: str | None = None
    notes: str | None = None


class FlagGoldPageRequest(BaseModel):
    reviewer_id: str
    notes: str


def create_gold_review_app(packet_dir: str | Path, annotations_dir: str | Path) -> FastAPI:
    session = GoldReviewSession(packet_dir, annotations_dir)
    app = FastAPI(
        title="Gold Sample v1 Human Review",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return GOLD_REVIEW_UI_HTML

    @app.get("/api/state")
    def state() -> dict:
        return session.list_pages()

    @app.get("/api/pages/{page_number}")
    def page(page_number: int) -> dict:
        try:
            return session.get_page(page_number)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/pages/{page_number}/image")
    def page_image(page_number: int) -> FileResponse:
        try:
            path = session.image_path(page_number)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(path, headers={"Cache-Control": "private, max-age=300"})

    @app.post("/api/pages/{page_number}/verify")
    def verify(page_number: int, request: VerifyGoldPageRequest) -> dict:
        try:
            return session.verify_page(
                page_number,
                reviewer_id=request.reviewer_id,
                checks=request.checks,
                records=request.records,
                page_classification=request.page_classification,
                notes=request.notes,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/pages/{page_number}/flag")
    def flag(page_number: int, request: FlagGoldPageRequest) -> dict:
        try:
            return session.flag_page(
                page_number,
                reviewer_id=request.reviewer_id,
                notes=request.notes,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    return app
