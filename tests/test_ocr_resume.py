import json
import threading

import fitz
import pytest

from app.adapters.consensus import ConsensusOcrAdapter, FileRowReader
from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.db import SessionLocal
from app.idr import BoundingBox, TextBlock
from app.models import ProcessingRun, SourceBlock
from app.services.ocr_extraction import extract_ocr_blocks


class CountingOcr:
    name = "counting"
    version = "1"

    def __init__(self, fail_on: int | None = None) -> None:
        self.fail_on = fail_on
        self.pages: list[int] = []
        self.threads: set[int] = set()
        self._lock = threading.Lock()

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        if page.page_number == self.fail_on:
            raise RuntimeError("engine crashed")
        with self._lock:
            self.pages.append(page.page_number)
            self.threads.add(threading.get_ident())
        return OcrPageResult(
            page_number=page.page_number,
            blocks=[
                TextBlock(
                    text=f"line of page {page.page_number}",
                    bbox=BoundingBox(0.1, 0.1, 0.9, 0.2),
                    reading_order=0,
                    confidence=0.99,
                )
            ],
            engine_name=self.name,
            engine_version=self.version,
            metadata={"document_sha256": page.document_sha256},
        )


def _upload(client, pages: int) -> str:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    payload = doc.tobytes()
    doc.close()
    return client.post(
        "/api/v1/documents", files={"file": ("scan.pdf", payload, "application/pdf")}
    ).json()["run_id"]


def _texts(db, run_id):
    return sorted(
        block.raw_text
        for block in db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id)
    )


def test_interrupted_ocr_keeps_finished_pages_and_resumes_at_the_next_one(client):
    run_id = _upload(client, 5)
    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError, match="engine crashed"):
            extract_ocr_blocks(db, run_id, CountingOcr(fail_on=4))
        db.rollback()
        progress = db.get(ProcessingRun, run_id).metrics["ocr_progress"]
        assert (progress["done"], progress["total"]) == ([1, 2, 3], 5)
        assert len(_texts(db, run_id)) == 3

        resumed = CountingOcr()
        result = extract_ocr_blocks(db, run_id, resumed)
        assert resumed.pages == [4, 5]  # finished pages are not read again
        assert (result["page_count"], result["block_count"], result["reused"]) == (5, 5, False)
        assert _texts(db, run_id) == [f"line of page {n}" for n in range(1, 6)]

        again = CountingOcr()
        assert extract_ocr_blocks(db, run_id, again)["reused"] is True
        assert again.pages == []
    finally:
        db.close()


def test_pages_are_read_in_parallel_by_separate_engines_and_stored_once(client):
    run_id = _upload(client, 8)
    db = SessionLocal()
    engines: list[CountingOcr] = []

    def factory() -> CountingOcr:
        engines.append(CountingOcr())
        return engines[-1]

    try:
        result = extract_ocr_blocks(
            db, run_id, CountingOcr(), page_workers=3, adapter_factory=factory
        )
        assert result["block_count"] == 8
        assert _texts(db, run_id) == [f"line of page {n}" for n in range(1, 9)]
        assert 1 <= len(engines) <= 3
        assert sorted(page for engine in engines for page in engine.pages) == list(range(1, 9))
        # No engine instance was ever used from two threads.
        assert all(len(engine.threads) == 1 for engine in engines)
        assert db.get(ProcessingRun, run_id).metrics["ocr_progress"]["done"] == list(range(1, 9))
    finally:
        db.close()


def test_imported_readings_vote_by_document_and_page(tmp_path):
    sha = "a" * 64
    folder = tmp_path / sha / "macos-vision"
    folder.mkdir(parents=True)
    (folder / "p0002.json").write_text(
        json.dumps([{"text": "回昧无穷", "x1": 0.1, "y1": 0.1, "x2": 0.9, "y2": 0.2}]),
        encoding="utf-8",
    )
    reader = FileRowReader("macos-vision", tmp_path)

    class Primary(CountingOcr):
        def extract_page(self, page):
            result = super().extract_page(page)
            result.blocks[0].text = "回味无穷"
            return result

    adapter = ConsensusOcrAdapter(Primary(), [reader])
    read = adapter.extract_page(OcrPageInput(page_number=2, image_bytes=b"", document_sha256=sha))
    assert read.blocks[0].metadata["consensus"]["status"] == "DISPUTED"
    assert read.blocks[0].metadata["consensus"]["other_readings"] == {"macos-vision": "回昧无穷"}
    # A page the reader has no file for, or another document: it abstains.
    for page in (
        OcrPageInput(page_number=3, image_bytes=b"", document_sha256=sha),
        OcrPageInput(page_number=2, image_bytes=b"", document_sha256="b" * 64),
        OcrPageInput(page_number=2, image_bytes=b""),
    ):
        status = adapter.extract_page(page).blocks[0].metadata["consensus"]["status"]
        assert status == "SINGLE_READER"
