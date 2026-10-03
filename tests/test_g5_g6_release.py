import hashlib
import time

from app.db import SessionLocal
from app.models import Artifact
from app.services.extraction import extract_native_blocks
from app.services.gates import evaluate_g5_review_resolution, evaluate_g6_gold_publication
from app.services.gold import (
    build_gold_dataset,
    publish_gold_release,
    serialize_gold_csv,
    serialize_gold_json,
    serialize_gold_xlsx,
)
from app.services.segmentation import segment_source_entries
from app.services.structured_extraction import extract_canonical_fields
from app.services.validation import validate_canonical_entries
from app.storage import LocalStorageAdapter


def test_g5_g6_and_gold_release_are_deterministic(client, sample_pdf_bytes, tmp_path):
    response = client.post("/api/v1/documents", files={"file": ("release.pdf", sample_pdf_bytes, "application/pdf")})
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    db = SessionLocal()
    try:
        extract_native_blocks(db, run_id); segment_source_entries(db, run_id); extract_canonical_fields(db, run_id); validate_canonical_entries(db, run_id)
        assert evaluate_g5_review_resolution(db, run_id)["status"] == "PASS"
        assert evaluate_g6_gold_publication(db, run_id)["status"] == "PASS"
        dataset = build_gold_dataset(db, run_id); json_a = serialize_gold_json(dataset); json_b = serialize_gold_json(dataset)
        assert json_a == json_b
        assert serialize_gold_csv(dataset).startswith(b"id,lemma,language,verification_status")
        xlsx_a = serialize_gold_xlsx(dataset)
        time.sleep(1.1)
        xlsx_b = serialize_gold_xlsx(dataset)
        assert xlsx_a == xlsx_b
        assert xlsx_a.startswith(b"PK")
        storage = LocalStorageAdapter(tmp_path / "gold-storage")
        release_a = publish_gold_release(db, run_id, storage); release_b = publish_gold_release(db, run_id, storage)
        assert release_a.id == release_b.id
        assert release_a.sha256 == hashlib.sha256(json_a).hexdigest()
        assert release_a.record_count == dataset["record_count"]
        assert release_a.json_artifact_id is not None
        assert release_a.csv_artifact_id is not None
        assert release_a.xlsx_artifact_id is not None
        json_artifact = db.get(Artifact, release_a.json_artifact_id)
        csv_artifact = db.get(Artifact, release_a.csv_artifact_id)
        xlsx_artifact = db.get(Artifact, release_a.xlsx_artifact_id)
        assert json_artifact is not None and storage.exists(json_artifact.object_key)
        assert csv_artifact is not None and storage.exists(csv_artifact.object_key)
        assert xlsx_artifact is not None and storage.exists(xlsx_artifact.object_key)
        assert storage.read_bytes(json_artifact.object_key) == json_a
        assert storage.read_bytes(csv_artifact.object_key) == serialize_gold_csv(dataset)
        assert storage.read_bytes(xlsx_artifact.object_key) == serialize_gold_xlsx(dataset)
    finally:
        db.close()
