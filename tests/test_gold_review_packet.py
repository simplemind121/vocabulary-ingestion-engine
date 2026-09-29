import hashlib
import json
from pathlib import Path

import pytest

from app.services.gold_review_packet import write_review_packet


def _drafts_and_images(tmp_path: Path):
    drafts = []
    images = {}
    for page in range(1, 31):
        payload = f"private-render-{page}".encode()
        image = tmp_path / f"source-{page}.png"
        image.write_bytes(payload)
        images[page] = image
        drafts.append(
            {
                "annotation_schema_version": "1.0",
                "sample_id": f"gold-v1-p{page:04d}",
                "document_sha256": "a" * 64,
                "page_number": page,
                "page_image_sha256": hashlib.sha256(payload).hexdigest(),
                "layout_tags": ["NORMAL"],
                "review_status": "DRAFT",
                "reviewer_id": None,
                "blocks": [{"text": "word", "confidence": 0.99}],
                "entries": [{"lemma": "word", "raw_text": "word"}],
                "vocabulary": [
                    {
                        "lemma": "word",
                        "ipa": "wɜːd",
                        "part_of_speech": "n.",
                        "definition": "词",
                    }
                ],
                "review_notes": ["MACHINE_PREANNOTATION_ONLY"],
            }
        )
    return drafts, images


def test_writes_private_source_vs_machine_packet_without_promoting_review(tmp_path):
    drafts, images = _drafts_and_images(tmp_path)
    output = tmp_path / "packet"

    packet = write_review_packet(drafts, images, output)

    assert packet["page_count"] == 30
    assert packet["human_verified_count"] == 0
    assert packet["review_status"] == "DRAFT"
    assert len(list((output / "annotations").glob("*.json"))) == 30
    assert len(list((output / "page-images").glob("*.png"))) == 30
    assert "source vs machine" in (output / "index.html").read_text(encoding="utf-8")
    saved = json.loads((output / "annotations" / "gold-v1-p0001.json").read_text())
    assert saved["review_status"] == "DRAFT"
    assert saved["reviewer_id"] is None


def test_packet_fails_closed_on_render_hash_drift(tmp_path):
    drafts, images = _drafts_and_images(tmp_path)
    images[8].write_bytes(b"changed")

    with pytest.raises(ValueError, match="page_image_sha256_mismatch:8"):
        write_review_packet(drafts, images, tmp_path / "packet")


def test_packet_rejects_machine_promoted_annotation(tmp_path):
    drafts, images = _drafts_and_images(tmp_path)
    drafts[0]["review_status"] = "HUMAN_VERIFIED"
    drafts[0]["reviewer_id"] = "not-allowed-here"

    with pytest.raises(ValueError, match="review_packet_accepts_draft_only:1"):
        write_review_packet(drafts, images, tmp_path / "packet")
