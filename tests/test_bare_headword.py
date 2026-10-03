import fitz

from app.adapters.pdf_native import PyMuPDFNativeAdapter
from app.db import SessionLocal
from app.models import (
    Definition,
    Pronunciation,
    ProvenanceRecord,
    Sense,
    SourceEntry,
    VocabularyEntry,
)
from app.services.extraction import extract_native_blocks
from app.services.field_parser import parse_source_entry
from app.services.segmentation import _segment_blocks, segment_source_entries
from app.services.structured_extraction import extract_canonical_fields, parse_source_entry_text
from app.services.validation import validate_canonical_entries


class FakeBlock:
    def __init__(self, block_id: str, page_id: str, text: str, bold: list[str] | None = None):
        self.id = block_id
        self.page_id = page_id
        self.raw_text = text
        self.metadata_json = {"bold_lines": bold} if bold else {}


def test_bold_headword_without_inline_ipa_starts_its_own_entry():
    blocks = [
        FakeBlock("b1", "p1", "tunnel* [ˈtʌnl]\nn. 隧道；地道\n例 The prisoner escaped."),
        FakeBlock("b2", "p1", "contrast", bold=["contrast"]),
        FakeBlock("b3", "p1", "[ˈkɒntrɑːst] n. 对比；对照\n[kənˈtrɑːst] v. 对比；形成对比"),
        FakeBlock("b4", "p1", "effect* [ɪˈfekt]\nn. 作用"),
    ]
    entries = _segment_blocks(blocks, {"p1": 300})
    assert [entry.lemma for entry in entries] == ["tunnel", "contrast", "effect"]
    assert "contrast" not in entries[0].raw_text
    assert entries[1].block_ids == ["b2", "b3"]


def test_starred_bold_headword_at_page_end_continues_on_next_page():
    blocks = [
        FakeBlock("b1", "p1", "aspect [ˈæspekt]\nn. 方面"),
        FakeBlock("b2", "p1", "compound*", bold=["compound*"]),
        FakeBlock("b3", "p1", "735"),
        FakeBlock("b4", "p2", "[kəmˈpaʊnd] vt. 使恶化\n[ˈkɒmpaʊnd] n. 化合物"),
    ]
    entries = _segment_blocks(blocks, {"p1": 735, "p2": 736})
    assert [entry.lemma for entry in entries] == ["aspect", "compound"]
    assert entries[1].starred is True
    assert entries[1].page_numbers == [735, 736]


def test_non_bold_single_word_line_stays_inside_the_entry():
    # A wrapped example line or a preview-table cell is never a headword.
    blocks = [
        FakeBlock("b1", "p1", "aspect [ˈæspekt]\nn. 方面\n例 It interferes with\nreading"),
        FakeBlock(
            "b2", "p1", "Word List 2\n词根/词缀预习表\ndimension\nn. 尺寸\nextent* [ɪkˈstent]\nn. 范围"
        ),
    ]
    entries = _segment_blocks(blocks, {"p1": 1})
    assert [entry.lemma for entry in entries] == ["aspect", "extent"]
    assert entries[0].raw_text.endswith("reading")


def test_bare_headword_parses_every_pronunciation_and_sense():
    parsed = parse_source_entry(
        ["contrast", "[ˈkɒntrɑːst] n. 对比；对照", "[kənˈtrɑːst] v. 对比；形成对比", "搭 by contrast 对比之下"]
    )
    assert parsed.lemma == "contrast"
    assert parsed.ipa == "ˈkɒntrɑːst"
    assert parsed.pronunciations == ["ˈkɒntrɑːst", "kənˈtrɑːst"]
    assert parsed.senses == [
        {"pos": "n.", "definition": "对比；对照"},
        {"pos": "v.", "definition": "对比；形成对比"},
    ]
    assert parsed.collocations == ["by contrast 对比之下"]


def test_bare_headword_without_any_printed_ipa():
    parsed = parse_source_entry_text("whisper\nn./v. 低语\n记 联想记忆")
    assert (parsed.lemma, parsed.ipa, parsed.part_of_speech, parsed.definition) == (
        "whisper",
        None,
        "n./v.",
        "低语",
    )


def test_wrapped_usage_label_is_not_a_pronunciation():
    parsed = parse_source_entry(["spare [speə(r)]", "adj. 闲置的 n. 备用品；", "[pl.] 配件"])
    assert parsed.pronunciations == ["speə(r)"]
    assert parsed.senses[0]["definition"].endswith("[pl.] 配件")


def test_native_adapter_records_bold_only_lines():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "contrast", fontname="hebo")
    page.insert_text((72, 110), "plain body text", fontname="helv")
    blocks = PyMuPDFNativeAdapter().extract_page(page)
    doc.close()
    by_text = {block.text: block.metadata for block in blocks}
    assert by_text["contrast"]["bold_lines"] == ["contrast"]
    assert "bold_lines" not in by_text["plain body text"]


def test_multiple_pronunciations_and_senses_persist_with_provenance(client):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "tunnel [tanl]", fontname="helv")
    page.insert_text((72, 100), "n. passage", fontname="helv")
    page.insert_text((72, 160), "contrast", fontname="hebo")
    page.insert_text((72, 220), "[kontrast] n. difference", fontname="helv")
    page.insert_text((72, 248), "[kantrast] v. compare", fontname="helv")
    payload = doc.tobytes()
    doc.close()
    run_id = client.post(
        "/api/v1/documents", files={"file": ("bare.pdf", payload, "application/pdf")}
    ).json()["run_id"]

    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        segment_source_entries(db, run_id)
        entries = (
            db.query(SourceEntry)
            .filter(SourceEntry.processing_run_id == run_id)
            .order_by(SourceEntry.entry_order)
            .all()
        )
        assert [entry.raw_text.splitlines()[0] for entry in entries] == ["tunnel [tanl]", "contrast"]
        assert extract_canonical_fields(db, run_id)["review_required"] == 0
        validate_canonical_entries(db, run_id)

        vocab = db.query(VocabularyEntry).filter(VocabularyEntry.source_entry_id == entries[1].id).one()
        assert vocab.lemma == "contrast"
        assert vocab.verification_status == "AUTO_VERIFIED"
        pronunciations = (
            db.query(Pronunciation)
            .filter(Pronunciation.vocabulary_entry_id == vocab.id)
            .order_by(Pronunciation.pronunciation_order)
            .all()
        )
        assert [item.ipa for item in pronunciations] == ["kontrast", "kantrast"]
        senses = (
            db.query(Sense)
            .filter(Sense.vocabulary_entry_id == vocab.id)
            .order_by(Sense.sense_order)
            .all()
        )
        assert [sense.part_of_speech for sense in senses] == ["n.", "v."]
        definitions = [db.query(Definition).filter(Definition.sense_id == sense.id).one() for sense in senses]
        assert [item.text for item in definitions] == ["difference", "compare"]
        for entity_type, entity_id in [
            *[("Pronunciation", item.id) for item in pronunciations],
            *[("Sense", item.id) for item in senses],
            *[("Definition", item.id) for item in definitions],
        ]:
            assert (
                db.query(ProvenanceRecord)
                .filter(
                    ProvenanceRecord.target_entity_type == entity_type,
                    ProvenanceRecord.target_entity_id == entity_id,
                    ProvenanceRecord.provenance_type == "SOURCE_DIRECT",
                )
                .count()
                == 1
            )
    finally:
        db.close()
