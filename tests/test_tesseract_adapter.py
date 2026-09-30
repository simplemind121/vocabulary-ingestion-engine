import subprocess

import pytest

from app.adapters.ocr_base import OcrPageInput
from app.adapters.tesseract import TesseractOcrAdapter

TSV = b"""level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext
1\t1\t0\t0\t0\t0\t0\t0\t200\t100\t-1\t
5\t1\t1\t1\t1\t1\t20\t10\t70\t20\t98.0\tvocabulary
5\t1\t1\t1\t1\t2\t100\t10\t80\t20\t96.0\tengine
"""


def _runner(command, **kwargs):
    del kwargs
    if "--version" in command:
        return subprocess.CompletedProcess(command, 0, b"tesseract 5.5.0\n", b"")
    return subprocess.CompletedProcess(command, 0, TSV, b"")


def test_tesseract_adapter_groups_words_and_normalizes_geometry():
    adapter = TesseractOcrAdapter(languages="eng+chi_sim", runner=_runner)

    result = adapter.extract_page(OcrPageInput(page_number=7, image_bytes=b"png"))

    assert result.engine_name == "tesseract"
    assert result.engine_version == "5.5.0"
    assert result.metadata["languages"] == "eng+chi_sim"
    assert len(result.blocks) == 1
    block = result.blocks[0]
    assert block.text == "vocabulary engine"
    assert block.confidence == pytest.approx(0.97)
    assert block.bbox.as_dict() == {
        "x1": 0.1,
        "y1": 0.1,
        "x2": 0.9,
        "y2": 0.3,
        "unit": "normalized",
    }


def test_tesseract_adapter_surfaces_engine_failure():
    def failed(command, **kwargs):
        del kwargs
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, b"tesseract 5.5.0\n", b"")
        return subprocess.CompletedProcess(command, 1, b"", b"missing language data")

    adapter = TesseractOcrAdapter(runner=failed)

    with pytest.raises(RuntimeError, match="missing language data"):
        adapter.extract_page(OcrPageInput(page_number=1, image_bytes=b"png"))
