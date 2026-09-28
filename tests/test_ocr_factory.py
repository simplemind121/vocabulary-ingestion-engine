import pytest

from app.services.ocr_factory import build_ocr_adapter
from app.settings import Settings


def test_ocr_factory_disables_engine_by_default():
    assert build_ocr_adapter(Settings()) is None


def test_ocr_factory_rejects_unknown_engine():
    with pytest.raises(ValueError, match="unsupported OCR engine"):
        build_ocr_adapter(Settings(ocr_engine="unknown"))
