import fitz

from app.adapters.pdf_native import PyMuPDFNativeAdapter


def test_native_adapter_extracts_normalized_text_blocks():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "abandon /əˈbændən/ v. to leave")
    blocks = PyMuPDFNativeAdapter().extract_page(page)
    doc.close()

    assert blocks
    assert "abandon" in blocks[0].text
    assert blocks[0].bbox.unit == "normalized"
    assert 0 <= blocks[0].bbox.x1 <= blocks[0].bbox.x2 <= 1
    assert 0 <= blocks[0].bbox.y1 <= blocks[0].bbox.y2 <= 1
