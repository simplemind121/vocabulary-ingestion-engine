from app.services.book_structure import classify_book_text
from app.services.field_parser import parse_source_entry


def test_real_book_headword_and_star_are_detected():
    result = classify_book_text("medication* [ˌmedɪˈkeɪʃn]")
    assert result.block_type == "ENTRY_HEAD"
    assert result.metadata["lemma"] == "medication"
    assert result.metadata["starred"] is True
    assert result.metadata["ipa"] == "ˌmedɪˈkeɪʃn"


def test_preview_table_words_are_not_entry_heads_when_context_is_known():
    result = classify_book_text("synthetic adj. 合成的", in_preview_table=True)
    assert result.block_type == "PREVIEW_TABLE"


def test_real_book_marked_fields_are_preserved_without_enrichment():
    parsed = parse_source_entry(
        [
            "medication* [ˌmedɪˈkeɪʃn]",
            "n. 药；药物",
            "记 词根记忆：med（治疗）+ication→药；药物",
            "搭 be on medication for sth. 因…而吃药",
            "例 The doctor writes what medication you need on the prescription. 医生在处方上写了你需要吃的药。",
        ]
    )
    assert parsed.lemma == "medication"
    assert parsed.starred is True
    assert parsed.ipa == "ˌmedɪˈkeɪʃn"
    assert parsed.senses == [{"pos": "n.", "definition": "药；药物"}]
    assert parsed.memory_notes == ["词根记忆：med（治疗）+ication→药；药物"]
    assert parsed.collocations == ["be on medication for sth. 因…而吃药"]
    assert len(parsed.examples) == 1
    assert not parsed.derivatives


def test_compound_part_of_speech_remains_source_exact():
    parsed = parse_source_entry(
        [
            "interview* [ˈɪntəvjuː]",
            "v./n. 接见，会见；采访；面试",
        ]
    )

    assert parsed.senses == [
        {"pos": "v./n.", "definition": "接见，会见；采访；面试"}
    ]


def test_derivative_synonym_and_antonym_fields_remain_separate():
    parsed = parse_source_entry(
        [
            "identify* [aɪˈdentɪfaɪ]",
            "v. 认出，识别；辨别；查明；确定；视…（与…）为同一事物",
            "搭 identify...with... 把…与…视为同一事物",
            "派 identifiable （adj. 可辨认的；可确认的）",
            "同 recognize （vt. 认出，识别）；determine （v. 确定）；distinguish （v. 区别，辨别）",
            "反 unknown （adj. 未知的）",
        ]
    )
    assert parsed.derivatives == ["identifiable （adj. 可辨认的；可确认的）"]
    assert parsed.synonyms[0].startswith("recognize")
    assert parsed.antonyms == ["unknown （adj. 未知的）"]


def test_word_list_and_page_numbers_are_not_vocabulary_entries():
    assert classify_book_text("Word List 47").block_type == "WORD_LIST_HEADER"
    assert classify_book_text("855").block_type == "PAGE_NUMBER"
    assert classify_book_text("词根/词缀预习表").block_type == "PREVIEW_TABLE_HEADER"
