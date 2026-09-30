import json

from fastapi.testclient import TestClient

from app.gold_review_server import create_gold_review_app
from app.services.gold_review_session import REQUIRED_HUMAN_CHECKS, GoldReviewSession


def _review_packet(
    tmp_path,
    *,
    blocks=None,
    entries=None,
    vocabulary=None,
    layout_tags=None,
):
    packet = tmp_path / "packet"
    (packet / "annotations").mkdir(parents=True)
    (packet / "page-images").mkdir()
    (packet / "page-images" / "page.png").write_bytes(b"png")
    annotation = {
        "annotation_schema_version": "1.0",
        "sample_id": "gold-v1-p0030",
        "document_sha256": "a" * 64,
        "page_number": 30,
        "layout_tags": layout_tags or ["NORMAL"],
        "review_status": "DRAFT",
        "reviewer_id": None,
        "page_image_sha256": "b" * 64,
        "blocks": blocks
        if blocks is not None
        else [
            {
                "source_block_id": "block-1",
                "text": "abandon",
                "raw_text": "abandon",
                "block_type": "TEXT",
            }
        ],
        "entries": entries
        if entries is not None
        else [
            {
                "lemma": "abandon",
                "raw_text": "abandon [ipa] v. leave",
                "source_pages": [30],
                "continuation_type": None,
            }
        ],
        "vocabulary": vocabulary
        if vocabulary is not None
        else [
            {
                "lemma": "abandon",
                "display_form": "abandon",
                "ipa": "ipa",
                "part_of_speech": "v.",
                "definition": "leave",
            }
        ],
        "review_notes": ["machine draft"],
    }
    annotation_path = packet / "annotations" / "gold-v1-p0030.json"
    annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
    manifest = {
        "items": [
            {
                "page_number": 30,
                "page_image": "page-images/page.png",
                "annotation": "annotations/gold-v1-p0030.json",
                "review_flags": [],
            }
        ]
    }
    (packet / "packet.json").write_text(json.dumps(manifest), encoding="utf-8")
    return packet, annotation


def _record():
    return {
        "index": 0,
        "lemma": "abandon",
        "display_form": "abandon",
        "ipa": "əˈbændən",
        "part_of_speech": "v.",
        "definition": "leave",
        "continuation_type": None,
        "source_pages": [30],
    }


def test_gold_review_server_requires_all_checks_and_writes_explicit_signoff(tmp_path):
    packet, original = _review_packet(tmp_path)
    annotations = tmp_path / "annotations"
    client = TestClient(create_gold_review_app(packet, annotations))

    rejected = client.post(
        "/api/pages/30/verify",
        json={"reviewer_id": "human-1", "checks": [], "records": [_record()]},
    )
    accepted = client.post(
        "/api/pages/30/verify",
        json={
            "reviewer_id": "human-1",
            "checks": sorted(REQUIRED_HUMAN_CHECKS),
            "records": [_record()],
            "notes": "checked against source",
        },
    )

    assert rejected.status_code == 409
    assert accepted.status_code == 200
    assert accepted.json()["review_status"] == "HUMAN_VERIFIED"
    saved = json.loads((annotations / "gold-v1-p0030.json").read_text(encoding="utf-8"))
    assert saved["reviewer_id"] == "human-1"
    assert saved["vocabulary"][0]["ipa"] == "əˈbændən"
    assert any(note.startswith("HUMAN_SIGN_OFF:") for note in saved["review_notes"])
    assert json.loads(
        (packet / "annotations" / "gold-v1-p0030.json").read_text(encoding="utf-8")
    ) == original


def test_gold_review_session_requires_human_classification_for_no_block_page(tmp_path):
    packet, _ = _review_packet(
        tmp_path,
        blocks=[],
        entries=[],
        vocabulary=[],
        layout_tags=["IMAGE"],
    )
    session = GoldReviewSession(packet, tmp_path / "annotations")

    try:
        session.verify_page(
            30,
            reviewer_id="human-2",
            checks=sorted(REQUIRED_HUMAN_CHECKS),
            records=[],
            page_classification=None,
            notes=None,
        )
    except ValueError as exc:
        assert "explicit classification" in str(exc)
    else:
        raise AssertionError("no-block page must require explicit human classification")

    result = session.verify_page(
        30,
        reviewer_id="human-2",
        checks=sorted(REQUIRED_HUMAN_CHECKS),
        records=[],
        page_classification="IMAGE_ONLY",
        notes=None,
    )
    assert result["review_status"] == "HUMAN_VERIFIED"
    saved = json.loads((tmp_path / "annotations" / "gold-v1-p0030.json").read_text())
    assert saved["blocks"][0]["source_engine"] == "human-review"


def test_gold_review_flag_records_issue_without_promoting(tmp_path):
    packet, _ = _review_packet(tmp_path)
    session = GoldReviewSession(packet, tmp_path / "annotations")

    result = session.flag_page(30, reviewer_id="human-3", notes="entry boundary is wrong")

    assert result["review_status"] == "DRAFT"
    saved = json.loads((tmp_path / "annotations" / "gold-v1-p0030.json").read_text())
    assert saved["reviewer_id"] is None
    assert saved["review_notes"][-1].endswith(":entry boundary is wrong")


def test_gold_review_signs_the_effective_maintainer_corrected_draft(tmp_path):
    packet, draft = _review_packet(tmp_path)
    annotations = tmp_path / "annotations"
    annotations.mkdir()
    draft["entries"].append(
        {
            "lemma": "ability",
            "raw_text": "ability [ipa] n. skill",
            "source_pages": [30],
            "continuation_type": None,
        }
    )
    draft["vocabulary"].append(
        {
            "lemma": "ability",
            "display_form": "ability",
            "ipa": "əˈbɪləti",
            "part_of_speech": "n.",
            "definition": "skill",
        }
    )
    (annotations / "gold-v1-p0030.json").write_text(json.dumps(draft), encoding="utf-8")
    session = GoldReviewSession(packet, annotations)
    second = {
        "index": 1,
        "lemma": "ability",
        "display_form": "ability",
        "ipa": "əˈbɪləti",
        "part_of_speech": "n.",
        "definition": "skill",
        "continuation_type": None,
        "source_pages": [30],
    }

    result = session.verify_page(
        30,
        reviewer_id="human-4",
        checks=sorted(REQUIRED_HUMAN_CHECKS),
        records=[_record(), second],
        page_classification=None,
        notes="maintainer correction checked",
    )

    assert result["review_status"] == "HUMAN_VERIFIED"
    assert len(result["records"]) == 2


def test_gold_review_rejects_identity_drift_from_frozen_packet(tmp_path):
    packet, draft = _review_packet(tmp_path)
    annotations = tmp_path / "annotations"
    annotations.mkdir()
    draft["document_sha256"] = "c" * 64
    (annotations / "gold-v1-p0030.json").write_text(json.dumps(draft), encoding="utf-8")
    session = GoldReviewSession(packet, annotations)

    try:
        session.get_page(30)
    except ValueError as exc:
        assert "frozen review packet" in str(exc)
    else:
        raise AssertionError("identity drift must fail closed")
