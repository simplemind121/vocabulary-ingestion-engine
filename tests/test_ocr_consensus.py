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
