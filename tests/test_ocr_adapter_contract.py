from app.adapters.ocr_base import OcrEngineAdapter, OcrPageInput, OcrPageResult
from app.idr import BoundingBox, TextBlock


class FakeOcrAdapter:
    name = "fake-ocr"
    version = "1.0"

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        return OcrPageResult(
            page_number=page.page_number,
            blocks=[
                TextBlock(
                    text="medication* [ˌmedɪˈkeɪʃn]",
                    bbox=BoundingBox(0.1, 0.1, 0.8, 0.2),
                    reading_order=0,
                    confidence=0.99,
                    metadata={"source": "ocr"},
                )
            ],
            engine_name=self.name,
            engine_version=self.version,
            metadata={"fixture": True},
        )


def _consume_adapter(adapter: OcrEngineAdapter) -> OcrPageResult:
    return adapter.extract_page(OcrPageInput(page_number=1, image_bytes=b"png"))


def test_ocr_adapter_contract_emits_engine_neutral_text_blocks():
    result = _consume_adapter(FakeOcrAdapter())
    assert result.page_number == 1
    assert result.engine_name == "fake-ocr"
    assert result.blocks[0].text.startswith("medication*")
    assert result.blocks[0].confidence == 0.99
    assert result.blocks[0].bbox.unit == "normalized"


def test_ocr_page_result_metadata_defaults_to_empty_dict():
    result = OcrPageResult(
        page_number=1,
        blocks=[],
        engine_name="fake",
        engine_version="1",
    )
    assert result.metadata == {}
