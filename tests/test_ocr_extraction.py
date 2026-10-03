import pytest

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.db import SessionLocal
from app.idr import BoundingBox, TextBlock
from app.models import SourceBlock
from app.services.ocr_extraction import extract_ocr_blocks


class FakeOcrAdapter:
    name = "fake"
    version = "1.0"

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        return OcrPageResult(
            page_number=page.page_number,
            blocks=[
                TextBlock(
                    text="medication* [ˌmedɪˈkeɪʃn]",
                    bbox=BoundingBox(0.1, 0.1, 0.8, 0.2),
                    reading_order=0,
                    confidence=0.98,
                    block_type="TEXT",
                    metadata={"fixture": True},
                ),
                TextBlock(
                    text="n. 药；药物",
                    bbox=BoundingBox(0.1, 0.2, 0.8, 0.3),
                    reading_order=1,
                    confidence=0.97,
                    block_type="TEXT",
                    metadata={"fixture": True},
                ),
            ],
            engine_name=self.name,
            engine_version=self.version,
            metadata={"mode": "test"},
        )


class ChangedOcrAdapter(FakeOcrAdapter):
    version = "2.0"


def test_ocr_extraction_persists_traceable_source_blocks(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("scan-fixture.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        result = extract_ocr_blocks(db, run_id, FakeOcrAdapter())
        assert result["page_count"] >= 1
        assert result["block_count"] >= 2
        assert result["mean_confidence"] > 0.9

        blocks = (
            db.query(SourceBlock)
            .filter(
                SourceBlock.processing_run_id == run_id,
                SourceBlock.source_engine == "ocr:fake",
            )
            .order_by(SourceBlock.reading_order)
            .all()
        )
        assert blocks[0].raw_text.startswith("medication*")
        assert blocks[0].confidence == 0.98
        assert blocks[0].bbox["unit"] == "normalized"
        assert blocks[0].page_id is not None
        assert blocks[0].source_engine_version == "1.0"
        assert blocks[0].metadata_json["ocr_result_metadata"]["mode"] == "test"
    finally:
        db.close()


def test_ocr_extraction_reuses_blocks_and_preserves_human_review(
    client, sample_pdf_bytes
):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("ocr-reuse.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        first = extract_ocr_blocks(db, run_id, FakeOcrAdapter())
        block = (
            db.query(SourceBlock)
            .filter(
                SourceBlock.processing_run_id == run_id,
                SourceBlock.source_engine == "ocr:fake",
            )
            .first()
        )
        assert block is not None
        block.metadata_json = {
            **(block.metadata_json or {}),
            "reviewed_text": "human reviewed text",
            "human_ocr_review": {"decision": "ACCEPT", "reviewer_id": "human-1"},
        }
        block_id = block.id
        db.commit()

        second = extract_ocr_blocks(db, run_id, FakeOcrAdapter())
        preserved = db.get(SourceBlock, block_id)

        assert first["reused"] is False
        assert second["reused"] is True
        assert second["block_count"] == first["block_count"]
        assert preserved is not None
        assert preserved.metadata_json["reviewed_text"] == "human reviewed text"
    finally:
        db.close()


def test_ocr_extraction_refuses_to_replace_human_reviewed_blocks(
    client, sample_pdf_bytes
):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("ocr-review-lock.pdf", sample_pdf_bytes, "application/pdf")},
    )
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        extract_ocr_blocks(db, run_id, FakeOcrAdapter())
        block = (
            db.query(SourceBlock)
            .filter(
                SourceBlock.processing_run_id == run_id,
                SourceBlock.source_engine == "ocr:fake",
            )
            .first()
        )
        assert block is not None
        block.metadata_json = {
            **(block.metadata_json or {}),
            "human_ocr_review": {"decision": "ACCEPT", "reviewer_id": "human-1"},
        }
        db.commit()

        with pytest.raises(ValueError, match="cannot replace human-reviewed OCR blocks"):
            extract_ocr_blocks(db, run_id, ChangedOcrAdapter())
    finally:
        db.close()
