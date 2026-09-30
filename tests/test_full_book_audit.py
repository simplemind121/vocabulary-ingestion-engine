import hashlib
from pathlib import Path

import fitz
import pytest

from app.services.full_book_audit import audit_full_book


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
