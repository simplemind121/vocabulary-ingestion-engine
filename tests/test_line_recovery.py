from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.db import SessionLocal
from app.idr import BoundingBox, TextBlock
from app.models import ReviewTask, SourceBlock
from app.services.ocr_quality import READERS_DISAGREE
from app.services.pipeline import run_pipeline
from app.services.unread_text import UNREAD_TEXT
from tests.test_unread_text import _scan


class BubbleBlindOcr:
    """Finds the first and last lines of the page; given the crop of the missed bubble, reads ``bubble``."""

    name = "bubble-blind"
    version = "1"

    def __init__(self, bubble: str) -> None:
        self.bubble = bubble
        self.crops = 0

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        if page.page_number == 0:
            self.crops += 1
            assert page.image_bytes.startswith(b"\x89PNG")
            lines = [(self.bubble, 0.1)]
        else:
            lines = [("Present continuous", 0.08), ("I am doing something now.", 0.81)]
        return OcrPageResult(
            page_number=page.page_number,
            blocks=[
                TextBlock(text=text, bbox=BoundingBox(0.05, top, 0.5, top + 0.03), reading_order=i, confidence=0.97)
                for i, (text, top) in enumerate(lines)
            ],
            engine_name=self.name,
            engine_version=self.version,
        )


def _run(client, tmp_path, adapter):
    source = tmp_path / "scan.pdf"
    _scan(source)
    run_id = client.post("/api/v1/documents", files={"file": ("scan.pdf", source.read_bytes(), "application/pdf")}).json()["run_id"]
    db = SessionLocal()
    result = run_pipeline(db, run_id, publish=False, ocr_adapter=adapter)
    return db, run_id, result


def _lines(db, run_id):
    return [b.raw_text for b in db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id).order_by(SourceBlock.reading_order)]


def test_a_missed_line_read_again_and_confirmed_joins_the_page_in_place(client, tmp_path):
    adapter = BubbleBlindOcr("Shall I open the window?")
    db, run_id, result = _run(client, tmp_path, adapter)
    try:
        stage = next(s["result"] for s in result["stages"] if s["stage"] == "line_recovery")
        assert stage["rows"] == 1 and stage["recovered"] == 1 and stage["confirmed"] == 1
        assert adapter.crops == 1
        assert _lines(db, run_id) == ["Present continuous", "Shall I open the window?", "I am doing something now."]
        recovered = db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id, SourceBlock.raw_text.like("Shall%")).one()
        assert recovered.metadata_json["recovered"]["text_layer"] == "Shall I open the window?"
        assert recovered.metadata_json["consensus"]["status"] == "UNANIMOUS"
        # The line is now read: nothing is left unread on the page.
        assert db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.reason_code == UNREAD_TEXT).count() == 0
    finally:
        db.close()


def test_a_missed_line_the_readers_disagree_on_goes_to_their_review(client, tmp_path):
    db, run_id, _ = _run(client, tmp_path, BubbleBlindOcr("Small owl pen the widow"))
    try:
        recovered = db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id, SourceBlock.metadata_json.isnot(None)).all()
        recovered = [b for b in recovered if "recovered" in (b.metadata_json or {})]
        assert len(recovered) == 1 and recovered[0].confidence <= 0.5
        assert recovered[0].metadata_json["consensus"]["status"] in {"DISPUTED", "SINGLE_READER"}
        task = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.reason_code == READERS_DISAGREE).one()
        assert task.target_entity_id == recovered[0].id
    finally:
        db.close()
