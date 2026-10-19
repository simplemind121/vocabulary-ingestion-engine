import fitz

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.db import SessionLocal
from app.idr import BoundingBox, TextBlock
from app.models import ReviewTask
from app.services.pipeline import run_pipeline
from app.services.unread_text import UNREAD_TEXT, find_unread_text, route_unread_text_reviews


def _scan(path) -> None:
    """One scanned page whose hidden OCR layer holds three lines, the middle one a speech bubble."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((30, 60), "Present continuous", fontsize=12, render_mode=3)
    page.insert_text((200, 300), "Shall I open the window?", fontsize=12, render_mode=3)
    page.insert_text((30, 500), "I am doing something now.", fontsize=12, render_mode=3)
    doc.save(path)
    doc.close()


def _line(top: float) -> dict:
    return {"x1": 0.05, "y1": top, "x2": 0.5, "y2": top + 0.03, "unit": "page"}


def test_text_outside_every_line_is_found(tmp_path):
    source = tmp_path / "scan.pdf"
    _scan(source)
    lines = [_line(0.08), _line(0.81)]
    rows = find_unread_text(source, 1, lines)
    assert [row["text"] for row in rows] == ["Shall I open the window?"]
    assert 0.45 < rows[0]["x1"] < rows[0]["x2"] <= 1 and 0.45 < rows[0]["y1"] < 0.5
    # With every line read, nothing is reported; beyond the last page the check abstains.
    assert find_unread_text(source, 1, [*lines, {"x1": 0.45, "y1": 0.46, "x2": 0.95, "y2": 0.51}]) == []
    assert find_unread_text(source, 2, lines) == []


def test_a_stray_mark_read_as_a_letter_is_not_text(tmp_path):
    source = tmp_path / "marks.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((30, 300), "CJ", fontsize=12, render_mode=3)
    page.insert_text((30, 400), "12 34", fontsize=12, render_mode=3)
    doc.save(source)
    doc.close()
    assert find_unread_text(source, 1, []) == []


class TwoLineOcr:
    """A primary reader that finds the first and last lines and misses the bubble; it reads nothing in a crop."""

    name = "two-lines"
    version = "1"

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        if page.page_number == 0:
            return OcrPageResult(page_number=0, blocks=[], engine_name=self.name, engine_version=self.version)
        return OcrPageResult(
            page_number=page.page_number,
            blocks=[
                TextBlock(text=text, bbox=BoundingBox(0.05, top, 0.5, top + 0.03), reading_order=order, confidence=0.99)
                for order, (text, top) in enumerate([("Present continuous", 0.08), ("I am doing something now.", 0.81)])
            ],
            engine_name=self.name,
            engine_version=self.version,
        )


def test_the_pipeline_parks_a_review_for_the_missed_line(client, tmp_path):
    source = tmp_path / "scan.pdf"
    _scan(source)
    run_id = client.post(
        "/api/v1/documents", files={"file": ("scan.pdf", source.read_bytes(), "application/pdf")}
    ).json()["run_id"]
    db = SessionLocal()
    try:
        result = run_pipeline(db, run_id, publish=False, ocr_adapter=TwoLineOcr())
        stage = next(s["result"] for s in result["stages"] if s["stage"] == "unread_text")
        assert stage["pages_with_unread_text"] == 1 and stage["unread_rows"] == 1
        tasks = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.reason_code == UNREAD_TEXT).all()
        assert len(tasks) == 1
        assert tasks[0].status == "DEFERRED" and tasks[0].target_entity_type == "Page"
        assert [row["text"] for row in tasks[0].source_context["rows"]] == ["Shall I open the window?"]
        # Running the check again does not repeat the review.
        route_unread_text_reviews(db, run_id)
        assert db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.reason_code == UNREAD_TEXT).count() == 1
    finally:
        db.close()
