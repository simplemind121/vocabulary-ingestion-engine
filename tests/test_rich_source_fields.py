from app.db import SessionLocal
from app.models import ProvenanceRecord, SourceEntry, VocabularyEntry, VocabularyField
from app.services.extraction import extract_native_blocks
from app.services.segmentation import segment_source_entries
from app.services.structured_extraction import extract_canonical_fields
from app.services.validation import validate_canonical_entries


def test_real_book_rich_fields_persist_with_source_provenance(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("rich.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id)
        segment_source_entries(db, run_id)
        source_entry = (
            db.query(SourceEntry)
            .filter(SourceEntry.processing_run_id == run_id)
            .first()
        )
        assert source_entry is not None
        source_entry.raw_text = (
            "medication* [ˌmedɪˈkeɪʃn]\n"
            "n. 药；药物\n"
            "记 词根记忆：med（治疗）+ication→药；药物\n"
            "搭 be on medication for sth. 因…而吃药\n"
            "例 The doctor writes what medication you need on the prescription.\n"
            "派 medicated （adj. 含药的）\n"
            "同 medicine （n. 药）\n"
            "反 nonmedicated （adj. 不含药的）"
        )
        db.commit()

        result = extract_canonical_fields(db, run_id)
        assert result["review_required"] == 0

        vocab = (
            db.query(VocabularyEntry)
            .filter(VocabularyEntry.source_entry_id == source_entry.id)
            .one()
        )
        fields = (
            db.query(VocabularyField)
            .filter(VocabularyField.vocabulary_entry_id == vocab.id)
            .order_by(VocabularyField.field_type, VocabularyField.field_order)
            .all()
        )
        assert {field.field_type for field in fields} == {
            "MEMORY_NOTE",
            "COLLOCATION",
            "EXAMPLE",
            "DERIVATIVE",
            "SYNONYM",
            "ANTONYM",
        }

        for field in fields:
            provenance = (
                db.query(ProvenanceRecord)
                .filter(
                    ProvenanceRecord.target_entity_type == "VocabularyField",
                    ProvenanceRecord.target_entity_id == field.id,
                    ProvenanceRecord.target_field_path == "text",
                )
                .one()
            )
            assert provenance.source_entry_id == source_entry.id
            assert provenance.source_block_id is not None
            assert provenance.page_id is not None

        validation = validate_canonical_entries(db, run_id)
        assert validation["validation_issues"] == 0
        assert all(field.verification_status == "AUTO_VERIFIED" for field in fields)
    finally:
        db.close()
