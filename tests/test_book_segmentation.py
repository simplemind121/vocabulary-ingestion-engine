from app.services.segmentation import _segment_blocks


class FakeBlock:
    def __init__(self, block_id: str, page_id: str, text: str):
        self.id = block_id
        self.page_id = page_id
        self.raw_text = text


def test_real_book_multiline_entries_are_grouped():
    blocks = [
        FakeBlock(
            "b1",
            "p1",
            "Word List 1\nmedication* [ˌmedɪˈkeɪʃn]\nn. 药；药物\n"
            "记 词根记忆：med（治疗）+ication→药；药物\n"
            "搭 be on medication for sth. 因…而吃药\n"
            "identify* [aɪˈdentɪfaɪ]\nv. 认出，识别",
        )
    ]
    entries = _segment_blocks(blocks, {"p1": 1})
    assert [entry.lemma for entry in entries] == ["medication", "identify"]
    assert entries[0].starred is True
    assert entries[0].word_list == 1
    assert "搭 be on medication" in entries[0].raw_text


def test_preview_table_rows_do_not_become_entries():
    blocks = [
        FakeBlock(
            "b1",
            "p1",
            "Word List 47\n词根/词缀预习表\nsynthetic adj. 合成的\npurify v. 净化\n"
            "medication* [ˌmedɪˈkeɪʃn]\nn. 药；药物",
        )
    ]
    entries = _segment_blocks(blocks, {"p1": 47})
    assert [entry.lemma for entry in entries] == ["medication"]


def test_entry_can_continue_across_page_boundary():
    blocks = [
        FakeBlock("b1", "p1", "medication* [ˌmedɪˈkeɪʃn]\nn. 药；药物"),
        FakeBlock("b2", "p2", "例 The doctor writes what medication you need."),
        FakeBlock("b3", "p2", "identify* [aɪˈdentɪfaɪ]\nv. 认出，识别"),
    ]
    entries = _segment_blocks(blocks, {"p1": 10, "p2": 11})
    assert entries[0].page_numbers == [10, 11]
    assert entries[0].block_ids == ["b1", "b2"]
    assert entries[1].page_numbers == [11]


def test_structured_book_does_not_turn_front_matter_words_into_legacy_entries():
    blocks = [
        FakeBlock("front", "p1", "CONTENTS\nUnit 1 Vocabulary"),
        FakeBlock("entry", "p2", "medication* [ˌmedɪˈkeɪʃn]\nn. 药；药物"),
    ]

    entries = _segment_blocks(blocks, {"p1": 1, "p2": 2})

    assert [entry.lemma for entry in entries] == ["medication"]


def test_appendix_header_terminates_dictionary_entry_and_suppresses_table_rows():
    blocks = [
        FakeBlock("entry", "p1", "solitary [ˈsɒlətri]\nadj. 孤独的"),
        FakeBlock("appendix", "p2", "一 雅思必备词根、词缀"),
        FakeBlock("table", "p2", "schedule [ˈʃedjuːl]\n[ˈskedʒuːl]"),
    ]

    entries = _segment_blocks(blocks, {"p1": 925, "p2": 926})

    assert [entry.lemma for entry in entries] == ["solitary"]
    assert entries[0].page_numbers == [925]
