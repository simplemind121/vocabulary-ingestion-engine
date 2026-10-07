from app.adapters.ocr_base import OcrPageInput
from app.adapters.paddleocr import PaddleOcrAdapter


class FakePaddleEngine:
    def ocr(self, image, cls=True):
        assert cls is False
        assert image.shape[0] == 100
        assert image.shape[1] == 200
        return [[
            [
                [[20.0, 10.0], [180.0, 10.0], [180.0, 30.0], [20.0, 30.0]],
                ("medication", 0.987),
            ]
        ]]


def test_paddleocr_adapter_normalizes_bbox_and_confidence():
    import io

    from PIL import Image

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


def _png(width=400, height=200):
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _box(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


class _Engine:
    def __init__(self, records):
        self.records = records

    def ocr(self, image, cls=True):
        return [self.records]


class _English:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def ocr(self, image, det=False, cls=False):
        self.calls += 1
        return [[(self.text, 0.97)]]


def test_restore_spaces_only_adopts_whitespace_from_the_english_reading():
    from app.adapters.paddleocr import restore_spaces

    glued = "【例】Theboywonderedhowalittlethingwascomposedofthree"
    english = "[5l] The boy wondered how a little thing was composed of three"
    assert restore_spaces(glued, english) == (
        "【例】The boy wondered how a little thing was composed of three"
    )
    mixed = "rosebuds.这个小男孩想知道。Lynntookseveraldeepbreaths"
    assert restore_spaces(mixed, "rosebuds.ii Lynn took several deep breaths") == (
        "rosebuds.这个小男孩想知道。Lynn took several deep breaths"
    )
    # A disagreement on any letter leaves the first reading untouched.
    assert restore_spaces("Theboywonderedhow", "The boy wandered how") == "Theboywonderedhow"
    assert restore_spaces("compose[kampauz]vt.组成", "") == "compose[kampauz]vt.组成"
    assert restore_spaces("internationalization", "internationalization") == (
        "internationalization"
    )


def test_glued_english_lines_are_reread_and_rows_are_put_in_reading_order():
    from app.adapters.ocr_base import OcrPageInput
    from app.adapters.paddleocr import PaddleOcrAdapter

    english = _English("Some people have an objection to tea.")
    adapter = PaddleOcrAdapter(
        engine=_Engine(
            [
                [_box(200, 100, 380, 120), ("C)caution", 0.92)],
                [_box(20, 60, 380, 80), ("Somepeoplehaveanobjectiontotea.", 0.99)],
                [_box(20, 101, 180, 121), ("A)optimism", 0.95)],
                [_box(20, 20, 380, 40), ("objection[abd3ekfon]n.反对", 0.93)],
            ]
        ),
        english_engine=english,
    )
    result = adapter.extract_page(OcrPageInput(page_number=7, image_bytes=_png()))

    assert [block.text for block in result.blocks] == [
        "objection[abd3ekfon]n.反对",
        "Some people have an objection to tea.",
        "A)optimism C)caution",
    ]
    assert english.calls == 1
    assert [block.reading_order for block in result.blocks] == [0, 1, 2]
    assert result.blocks[1].metadata["english_spacing_restored"] is True
    assert result.blocks[0].metadata["english_spacing_restored"] is False
    merged = result.blocks[2]
    assert merged.confidence == 0.92
    assert (round(merged.bbox.x1, 3), round(merged.bbox.x2, 3)) == (0.05, 0.95)
