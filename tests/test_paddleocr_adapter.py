from app.adapters.ocr_base import OcrPageInput
from app.adapters.paddleocr import PaddleOcrAdapter


class FakePaddleEngine:
    def ocr(self, image, cls=True):
        assert cls is True
        assert image.shape[0] == 100
        assert image.shape[1] == 200
        return [[
            [
                [[20.0, 10.0], [180.0, 10.0], [180.0, 30.0], [20.0, 30.0]],
                ("medication", 0.987),
            ]
        ]]


def test_paddleocr_adapter_normalizes_bbox_and_confidence():
    from PIL import Image
    import io

    image = Image.new("RGB", (200, 100), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    adapter = PaddleOcrAdapter(engine=FakePaddleEngine())
    result = adapter.extract_page(OcrPageInput(page_number=7, image_bytes=buffer.getvalue()))

    assert result.page_number == 7
    assert result.engine_name == "paddleocr"
    assert len(result.blocks) == 1
    block = result.blocks[0]
    assert block.text == "medication"
    assert block.confidence == 0.987
    assert block.bbox.as_dict() == {
        "x1": 0.1,
        "y1": 0.1,
        "x2": 0.9,
        "y2": 0.3,
        "unit": "normalized",
    }
