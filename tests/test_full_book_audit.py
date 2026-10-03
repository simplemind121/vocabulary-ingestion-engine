import hashlib
from pathlib import Path

import fitz
import pytest

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.idr import BoundingBox, TextBlock
from app.services.full_book_audit import audit_full_book


class CoverOcr:
    name = "cover-ocr"
    version = "1.0"

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        return OcrPageResult(
            page_number=page.page_number,
            blocks=[
                TextBlock(
                    text="封面标题",
                    bbox=BoundingBox(0.1, 0.1, 0.9, 0.3),
                    reading_order=0,
                    confidence=0.99,
                )
            ],
            engine_name=self.name,
            engine_version=self.version,
        )


def _book(tmp_path: Path) -> Path:
    document = fitz.open()
    document.new_page()
    page = document.new_page()
    page.insert_text((72, 72), "sample* [ˈsɑːmpl]\nn. 样品")
    path = tmp_path / "book.pdf"
    document.save(path)
    document.close()
    return path


def test_whole_book_audit_reports_unrepresented_pages_and_real_entries(tmp_path):
    source = _book(tmp_path)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    report = audit_full_book(source, expected_sha256=digest, expected_page_count=2)

    assert report["status"] == "REVIEW_REQUIRED"
    assert report["source_page_count"] == 2
    assert report["unrepresented_pages"] == [1]
    assert report["entry_candidate_count"] == 1
    assert report["parsed_entry_count"] == 1


def test_whole_book_audit_rejects_wrong_source_identity(tmp_path):
    with pytest.raises(ValueError, match="source_document_sha256_mismatch"):
        audit_full_book(_book(tmp_path), expected_sha256="0" * 64, expected_page_count=2)


def test_whole_book_audit_uses_ocr_only_for_unrepresented_pages(tmp_path):
    source = _book(tmp_path)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    report = audit_full_book(
        source,
        expected_sha256=digest,
        expected_page_count=2,
        ocr_adapter=CoverOcr(),
    )

    assert report["status"] == "PASS"
    assert report["native_text_pages"] == 1
    assert report["ocr_pages_attempted"] == 1
    assert report["ocr_text_pages"] == 1
    assert report["page_representation_coverage"] == 1.0
    assert report["unrepresented_pages"] == []
    assert report["ocr_source_block_count"] == 1
