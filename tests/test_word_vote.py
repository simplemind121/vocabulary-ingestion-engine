import fitz
import pytest

from app.adapters.consensus import ConsensusOcrAdapter
from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.db import SessionLocal
from app.idr import BoundingBox, TextBlock
from app.models import ReviewTask, SourceBlock
from app.services.ocr_quality import READERS_DISAGREE
from app.services.pipeline import run_pipeline
from app.services.segmentation import _effective_block_text
from app.services.word_vote import WORD_MAJORITY, load_lexicon, settle_by_words, settle_parked_lines
from app.word_vote_cli import main as cli


@pytest.fixture
def lexicon(tmp_path):
    path = tmp_path / "ecdict.csv"
    rows = ["word,phonetic,definition,translation,pos,collins,oxford,tag,bnc,frq,exchange,detail,audio"]
    for word, bnc in [("shall", 900), ("open", 300), ("the", 1), ("window", 1200), ("lt", 9000), ("is", 5), ("raining", 4000), ("zyx", 0)]:
        rows.append(f"{word},,,,,,,,{bnc},{bnc},,,")
    path.write_text("\n".join(rows) + "\n")
    return path


def test_the_word_list_keeps_common_words_and_drops_misreadings(lexicon):
    words = load_lexicon(str(lexicon))
    assert {"shall", "window", "i", "don't"} <= words
    assert "zyx" not in words and "lt" not in words


def test_two_readers_agreeing_on_common_words_settle_the_line(lexicon):
    words = load_lexicon(str(lexicon))
    order = ["primary", "rapid", "vision"]
    agreed = settle_by_words({"primary": "Shall I open the window ?", "rapid": "Shall I open the window?", "vision": "Shal1 I open the wind0w"}, order, words)
    assert agreed == ("Shall I open the window ?", ["primary", "rapid"])
    # A shared misreading is not a common word; readers that all differ settle nothing.
    assert settle_by_words({"primary": "lt is raining", "rapid": "lt is raining."}, ["primary", "rapid"], words) is None
    assert settle_by_words({"primary": "Shall I", "rapid": "Shal I", "vision": "Shall l"}, order, words) is None


class Reader:
    def __init__(self, name, text):
        self.name, self._text = name, text

    def read_rows(self, page):
        return [{"text": self._text, "x1": 0.1, "y1": 0.1, "x2": 0.9, "y2": 0.14}]


class Primary:
    name = "primary"
    version = "1"

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        return OcrPageResult(page_number=page.page_number, blocks=[TextBlock(
            text="Shall I open the window ?", bbox=BoundingBox(0.1, 0.1, 0.9, 0.14), reading_order=0, confidence=0.95)],
            engine_name=self.name, engine_version=self.version)


def test_the_vote_settles_a_disputed_line_by_its_words(lexicon):
    adapter = ConsensusOcrAdapter(Primary(), [Reader("rapid", "Shall I open the window."), Reader("vision", "Sha11 l opeu tbe wiudow!")],
                                  lexicon=load_lexicon(str(lexicon)))
    block = adapter.extract_page(OcrPageInput(page_number=1, image_bytes=b"")).blocks[0]
    consensus = block.metadata["consensus"]
    assert consensus["status"] == WORD_MAJORITY and consensus["agreed_readers"] == ["primary", "rapid"]
    assert block.confidence == 0.95
    # Without the word list the same line stays disputed and capped.
    plain = ConsensusOcrAdapter(Primary(), [Reader("rapid", "Shall I open the window."), Reader("vision", "Sha11 l opeu tbe wiudow!")])
    assert plain.extract_page(OcrPageInput(page_number=1, image_bytes=b"")).blocks[0].metadata["consensus"]["status"] == "DISPUTED"


def test_parked_lines_of_an_existing_run_are_settled_before_arbitration(client, lexicon):
    doc = fitz.open()
    doc.new_page()
    payload = doc.tobytes()
    doc.close()
    run_id = client.post("/api/v1/documents", files={"file": ("p.pdf", payload, "application/pdf")}).json()["run_id"]
    adapter = ConsensusOcrAdapter(Primary(), [Reader("rapid", "Shall I open the window."), Reader("vision", "Sha11 l opeu tbe wiudow!")])
    db = SessionLocal()
    try:
        run_pipeline(db, run_id, publish=False, ocr_adapter=adapter)
        task = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.reason_code == READERS_DISAGREE).one()
        assert task.status in {"DEFERRED", "NOT_APPLICABLE"}
    finally:
        db.close()
    assert cli([run_id, "--lexicon", str(lexicon), "--dry-run"]) == 0
    db = SessionLocal()
    try:
        assert db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.status == "ARBITRATED").count() == 0
        result = settle_parked_lines(db, run_id, load_lexicon(str(lexicon)))
        assert result["settled"] == 1
        block = db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id).one()
        assert block.metadata_json["machine_arbitration"]["arbiter"] == "word-majority"
        assert _effective_block_text(block) == "Shall I open the window ?"
        assert db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id, ReviewTask.status == "ARBITRATED").count() == 1
    finally:
        db.close()
