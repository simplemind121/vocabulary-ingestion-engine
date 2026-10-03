import fitz

from app.services.gold_sample_selection import (
    profile_pdf_pages,
    select_gold_sample_candidates,
    summarize_candidate_coverage,
)


def test_pdf_page_profiler_detects_images_and_text(tmp_path):
    path = tmp_path / "profile.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "normal vocabulary page " * 40)
    page2 = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, 20, 20, b"\xff" * (20 * 20 * 3), 0)
    page2.insert_image(page2.rect, pixmap=pix)
    doc.save(path)
    doc.close()

    profiles = profile_pdf_pages(path)
    assert len(profiles) == 2
    assert profiles[0]["text_length"] >= 100
    assert profiles[0]["block_count"] >= 1
    assert profiles[1]["image_count"] >= 1
    assert "IMAGE" in profiles[1]["candidate_tags"]
    assert "OCR_HARD" in profiles[1]["candidate_tags"]
    assert "BOUNDARY_ENTRY" not in profiles[0]["candidate_tags"]
    assert "CROSS_PAGE_ENTRY" not in profiles[0]["candidate_tags"]


def test_candidate_selector_keeps_status_non_gold_until_visual_review():
    profiles = []
    tags = [
        "NORMAL",
        "DOUBLE_COLUMN",
        "IPA_DENSE",
        "IMAGE",
        "SPECIAL_LAYOUT",
        "BOUNDARY_ENTRY",
        "TABLE",
        "INDEX",
        "OCR_HARD",
    ]
    for index in range(30):
        profiles.append(
            {
                "page_number": index + 1,
                "text_length": 1000 - index,
                "block_count": 10 + index,
                "image_count": 1 if index == 3 else 0,
                "ipa_count": index,
                "double_column": index == 1,
                "table_signals": 3 if index == 6 else 0,
                "candidate_tags": [tags[index]] if index < len(tags) else ["NORMAL"],
            }
        )

    selected = select_gold_sample_candidates(profiles, target_pages=30)
    assert len(selected) == 30
    assert all(item["selection_status"] == "CANDIDATE_SELECTION" for item in selected)
    assert all(item["requires_visual_review"] is True for item in selected)

    coverage = summarize_candidate_coverage(selected)
    assert "CROSS_PAGE_ENTRY" in coverage["missing_layout_tags"]
