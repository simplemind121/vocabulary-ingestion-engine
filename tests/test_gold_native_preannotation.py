import hashlib
from pathlib import Path

import fitz
import pytest

from app.services.gold_native_preannotation import build_native_pdf_predictions


def _pdf(tmp_path: Path) -> Path:
    document = fitz.open()
    first = document.new_page()
    first.insert_text((72, 72), "alpha [ˈælfə] n. first letter")
    second = document.new_page()
    second.insert_text((72, 72), "beta [ˈbiːtə] n. second letter")
    path = tmp_path / "source.pdf"
    document.save(path)
    document.close()
    return path


def _scaffolds(source: Path, render_dir: Path):
    document = fitz.open(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    scaffolds = []
    for page_number in (1, 2):
        render = render_dir / f"expected-{page_number}.png"
        document[page_number - 1].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(render)
        scaffolds.append(
            {
                "document_sha256": source_sha,
                "page_number": page_number,
                "page_image_sha256": hashlib.sha256(render.read_bytes()).hexdigest(),
                "layout_tags": ["NORMAL"],
            }
        )
    document.close()
    return scaffolds


def test_builds_source_bound_native_predictions(tmp_path):
    source = _pdf(tmp_path)
    scaffolds = _scaffolds(source, tmp_path)

    predictions, images = build_native_pdf_predictions(source, scaffolds, tmp_path / "renders")

    assert [item["page_number"] for item in predictions] == [1, 2]
    assert all(item["blocks"] for item in predictions)
    assert predictions[0]["vocabulary"][0]["lemma"] == "alpha"
    assert predictions[1]["vocabulary"][0]["lemma"] == "beta"
    assert set(images) == {1, 2}


def test_rejects_wrong_source_document(tmp_path):
    source = _pdf(tmp_path)
    scaffolds = _scaffolds(source, tmp_path)
    scaffolds[0]["document_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="source_document_sha256_mismatch"):
        build_native_pdf_predictions(source, scaffolds, tmp_path / "renders")


def test_non_entry_layout_is_not_forced_through_vocabulary_segmenter(tmp_path):
    source = _pdf(tmp_path)
    scaffolds = _scaffolds(source, tmp_path)
    scaffolds[0]["layout_tags"] = ["TABLE", "SPECIAL_LAYOUT"]
    scaffolds[1]["layout_tags"] = ["NORMAL"]

    predictions, _ = build_native_pdf_predictions(source, scaffolds, tmp_path / "renders")

    assert predictions[0]["blocks"]
    assert predictions[0]["entries"] == []
    assert predictions[0]["vocabulary"] == []
    assert predictions[1]["vocabulary"][0]["lemma"] == "beta"
