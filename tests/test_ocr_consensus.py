from app.services.ocr_consensus import (
    DISPUTED,
    MAJORITY,
    SINGLE_READER,
    UNANIMOUS,
    build_consensus,
)


def test_typography_is_not_a_disagreement():
    result = build_consensus(
        "compose[kampauz]vt.组成，构成；创作（乐曲）",
        ["compose ［kam'pauz］ vt. 组成, 构成; 创作 (乐曲)", "compose[kəmpəuz]vt.组成，构成；创作（乐曲）"],
    )
    assert result.status == UNANIMOUS
    assert result.readers == 3
    assert result.text == "compose[kampauz]vt.组成，构成；创作（乐曲）"


def test_base_reading_stands_when_one_other_reader_seconds_it():
    # One engine reads the arrow as a CJK dash and drops the "t" of "vt.".
    result = build_consensus(
        "【记】com+pos→放到一起 vt.组成",
        ["【记】com+pos一放到一起 v.组成", "【记】com+pos→放到一起 vt.组成"],
    )
    assert result.status == MAJORITY
    assert result.text == "【记】com+pos→放到一起 vt.组成"
    assert result.corrections == [] and result.disputes == []


def test_two_readers_overrule_the_base_and_the_change_is_recorded():
    result = build_consensus(
        "intellectual[x]n.知识分子adj智力的团体",
        ["intellectual[y]n.知识分子adj.智力的困体", "intellectual [z] n.知识分子 adj.智力的困体"],
    )
    assert result.status == MAJORITY
    assert result.text == "intellectual[x]n.知识分子adj.智力的困体"
    assert {"from": "团", "to": "困"} in result.corrections
    assert {"from": "", "to": "."} in result.corrections


def test_three_different_readings_are_disputed_and_nothing_is_chosen():
    result = build_consensus("回味无穷", ["回昧无穷", "回未无穷"])
    assert result.status == DISPUTED
    assert result.text == "回味无穷"
    assert result.disputes == [{"base": "味", "others": ["昧", "未"]}]


def test_two_readers_that_disagree_cannot_settle_anything():
    result = build_consensus("强热带风暴", ["强热带飓风暴"])
    assert result.status == DISPUTED
    assert result.text == "强热带风暴"


def test_pronunciations_are_never_voted_on():
    result = build_consensus("fraud[fro：d]n.欺诈", ["fraud[fro:d]n.欺诈", "fraud[frɔːd]n.欺诈"])
    assert result.status == UNANIMOUS
    assert result.text == "fraud[fro：d]n.欺诈"


def test_a_reading_of_some_other_line_abstains():
    result = build_consensus("【例】Some people have an objection to tea.", ["21", ""])
    assert result.status == SINGLE_READER
    assert result.readers == 1
    alone = build_consensus("平静，使镇静", [])
    assert (alone.status, alone.text) == (SINGLE_READER, "平静，使镇静")


def _page_result(rows):
    from app.adapters.ocr_base import OcrPageResult
    from app.idr import BoundingBox, TextBlock

    return OcrPageResult(
        page_number=1,
        blocks=[
            TextBlock(
                text=text,
                bbox=BoundingBox(0.1, top, 0.9, top + 0.03),
                reading_order=order,
                confidence=0.97,
                metadata={},
            )
            for order, (top, text) in enumerate(rows)
        ],
        engine_name="primary",
        engine_version="1",
        metadata={},
    )


class _Primary:
    name = "primary"

    def __init__(self, rows):
        self.rows = rows

    def extract_page(self, page):
        return _page_result(self.rows)


class _Reader:
    def __init__(self, name, rows):
        self.name, self.rows = name, rows

    def read_rows(self, page):
        return [
            {"text": text, "x1": 0.1, "y1": top, "x2": 0.9, "y2": top + 0.03}
            for top, text in self.rows
        ]


def test_consensus_adapter_confirms_corrects_and_sends_the_rest_to_review():
    from app.adapters.consensus import ConsensusOcrAdapter
    from app.adapters.ocr_base import OcrPageInput

    adapter = ConsensusOcrAdapter(
        _Primary(
            [
                (0.10, "【例】Somepeoplehaveanobjectiontotea.有些人不喜欢喝茶。"),
                (0.20, "intellectual[x]n.知识分子adj智力的团体"),
                (0.30, "回味无穷"),
                (0.40, "只有主读者读到的一行"),
            ]
        ),
        [
            _Reader(
                "vision",
                [
                    (0.10, "【例】Some people have an objection to tea. 有些人不喜欢喝茶。"),
                    (0.20, "intellectual [y] n. 知识分子 adj. 智力的困体"),
                    (0.30, "回昧无穷"),
                ],
            ),
            _Reader(
                "v5",
                [
                    (0.10, "【例】Somepeoplehaveanobjectiontotea.有些人不喜欢喝茶。"),
                    (0.20, "intellectual[z]n.知识分子adj.智力的困体"),
                    (0.30, "回未无穷"),
                ],
            ),
        ],
    )
    blocks = adapter.extract_page(OcrPageInput(page_number=1, image_bytes=b"")).blocks
    status = [block.metadata["consensus"]["status"] for block in blocks]
    assert status == ["UNANIMOUS", "MAJORITY", "DISPUTED", "SINGLE_READER"]
    # Spacing comes from the reader that has it; the letters were unanimous.
    assert blocks[0].text == "【例】Some people have an objection to tea.有些人不喜欢喝茶。"
    assert blocks[1].text == "intellectual[x]n.知识分子adj.智力的困体"
    assert blocks[2].text == "回味无穷"
    assert [block.confidence for block in blocks] == [0.97, 0.97, 0.5, 0.5]
    assert blocks[2].metadata["consensus"]["other_readings"] == {
        "vision": "回昧无穷",
        "v5": "回未无穷",
    }
    assert adapter.version == "primary+vision+v5"


def test_factory_requires_a_url_for_the_vision_reader():
    import pytest

    from app.services.ocr_factory import build_ocr_adapter
    from app.settings import Settings

    assert build_ocr_adapter(Settings(ocr_engine="none", ocr_secondary_readers="vision")) is None
    with pytest.raises(ValueError, match="VIE_VISION_OCR_URL"):
        build_ocr_adapter(Settings(ocr_engine="tesseract", ocr_secondary_readers="vision"))
    adapter = build_ocr_adapter(
        Settings(
            ocr_engine="tesseract",
            ocr_secondary_readers="vision",
            vision_ocr_url="http://127.0.0.1:8791/ocr",
        )
    )
    assert adapter.name == "ocr-consensus"
    assert adapter.version == "tesseract+macos-vision"
