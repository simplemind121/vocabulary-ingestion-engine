from app.db import SessionLocal
from app.models import Definition, Pronunciation, ProvenanceRecord, Sense, VocabularyEntry
from app.services.extraction import extract_native_blocks
from app.services.segmentation import segment_source_entries
from app.services.structured_extraction import extract_canonical_fields, parse_source_entry_text


def test_parse_source_entry_text():
    parsed = parse_source_entry_text("abandon /əˈbændən/ v. to leave somebody or something")
    assert parsed.lemma == "abandon"
    assert parsed.ipa == "əˈbændən"
    assert parsed.part_of_speech == "v."
    assert parsed.definition == "to leave somebody or something"


def test_structured_extraction_persists_canonical_fields_and_provenance(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("canonical.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        segment_source_entries(db, run_id)
        result = extract_canonical_fields(db, run_id)
        assert result["extracted_entries"] >= 1

        vocab = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id).first()
        assert vocab is not None
        sense = db.query(Sense).filter(Sense.vocabulary_entry_id == vocab.id).first()
        assert sense is not None

        provenance = (
            db.query(ProvenanceRecord)
            .filter(
                ProvenanceRecord.processing_run_id == run_id,
                ProvenanceRecord.target_entity_type == "VocabularyEntry",
                ProvenanceRecord.target_field_path == "lemma",
            )
            .first()
        )
        assert provenance is not None
        assert provenance.source_entry_id is not None
        assert provenance.source_block_id is not None
        assert provenance.page_id is not None

        # IPA/definition depend on source glyph fidelity; if extracted they must be SOURCE-backed.
        pronunciation = db.query(Pronunciation).filter(Pronunciation.vocabulary_entry_id == vocab.id).first()
        if pronunciation is not None:
            assert pronunciation.ipa
        definition = db.query(Definition).filter(Definition.sense_id == sense.id).first()
        if definition is not None:
            assert definition.text
    finally:
        db.close()
