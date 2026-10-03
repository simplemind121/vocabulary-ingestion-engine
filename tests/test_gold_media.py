import copy
import json

import pytest
from fastapi.testclient import TestClient

from app.gold_media_cli import main as gate_main
from app.gold_review_server import create_gold_review_app
from app.services.gold_corpus import freeze_manifest
from app.services.gold_media import (
    GoldMediaReviewSession,
    build_media_draft,
    evaluate_media_readiness,
    evaluate_media_regression,
)
from tests.media_helpers import (
    media_item,
    media_predictions,
    source_media_evidence,
    verified_media_overlays,
)
from tests.test_release_readiness import _evaluate, _verified_annotations

CHECKS = ["compared_with_original_page", "no_source_media_missing", "every_association_checked"]


def _corpus():
    annotations = _verified_annotations()
    predictions = media_predictions(
        annotations,
        {
            2: [media_item(1, lemma="word", seed=11)],
            5: [media_item(1, lemma=None, seed=12), media_item(2, lemma=None, seed=13)],
        },
    )
    return annotations, predictions, verified_media_overlays(annotations, predictions)


def test_media_gate_passes_with_real_counts_and_zero_media_pages_verified():
    annotations, predictions, overlays = _corpus()
    report = evaluate_media_regression(annotations, overlays, predictions)
    assert report["status"] == "PASS"
    assert report["metrics"] == {
        "gold_pages_checked": 30,
        "gold_pages_total": 30,
        "pages_with_media": 2,
        "pages_verified_without_media": 28,
        "expected_source_media": 3,
        "detected_source_media": 3,
        "extracted_source_media": 3,
        "verified_source_media": 3,
        "correct_entry_association": 3,
        "unbound": 0,
        "unresolved": 0,
        "missing_sha256": 0,
    }


def test_machine_drafts_are_never_human_verified():
    annotations, predictions, _ = _corpus()
    drafts = [build_media_draft(a, p) for a, p in zip(annotations, predictions, strict=True)]
    assert {draft["review_status"] for draft in drafts} == {"DRAFT"}
    readiness = evaluate_media_readiness(annotations, drafts)
    assert readiness["status"] == "NOT_READY"
    assert readiness["gold_pages_checked"] == 0
    assert evaluate_media_regression(annotations, drafts, predictions)["status"] == "FAIL"
    with pytest.raises(ValueError, match="source media cannot freeze"):
        freeze_manifest(annotations, drafts)


@pytest.mark.parametrize(
    ("mutate", "blocker"),
    [
        (lambda p: p[1]["media"][0].update(lemma="other"), "media_regression_mismatch"),
        (lambda p: p[1]["media"].clear(), "media_regression_mismatch"),
        (lambda p: p[0]["media"].append(media_item(1, lemma="word", seed=99)), "media_regression_mismatch"),
        (lambda p: p[1]["media"][0].update(media_role="UNRESOLVED", lemma=None), "unresolved_media"),
        (lambda p: p[1]["media"][0].update(lemma=None), "unbound_media"),
        (lambda p: p[1]["media"][0].update(sha256=None), "missing_sha256"),
    ],
)
def test_media_gate_fails_on_wrong_missing_extra_or_unresolved_media(mutate, blocker):
    annotations, predictions, overlays = _corpus()
    mutate(predictions)
    report = evaluate_media_regression(annotations, overlays, predictions)
    assert report["status"] == "FAIL"
    assert blocker in report["blocking_failures"]


def test_media_manifest_supersedes_the_text_only_manifest():
    annotations, _, overlays = _corpus()
    text_only = freeze_manifest(annotations)
    complete = freeze_manifest(annotations, overlays)
    assert (text_only["dataset_version"], complete["dataset_version"]) == ("1.0", "1.1")
    assert text_only["manifest_sha256"] != complete["manifest_sha256"]
    for before, after in zip(text_only["pages"], complete["pages"], strict=True):
        assert after["ground_truth_sha256"] == before["ground_truth_sha256"]
        assert after["media_review_status"] == "HUMAN_VERIFIED"
    assert [page["media_count"] for page in complete["pages"]][:5] == [0, 1, 0, 0, 2]
    changed = copy.deepcopy(overlays)
    changed[1]["media"][0]["lemma"] = "other"
    assert freeze_manifest(annotations, changed)["manifest_sha256"] != complete["manifest_sha256"]


def test_g6_release_requires_media_gold_and_full_book_media_evidence():
    annotations = _verified_annotations()
    assert _evaluate(annotations)["status"] == "PASS"

    stale_manifest = _evaluate(annotations, manifest=freeze_manifest(annotations))
    assert "frozen_manifest_mismatch" in stale_manifest["blocking_failures"]

    no_media_review = _evaluate(annotations, media_annotations=[])
    assert "gold_source_media_gate_failed" in no_media_review["blocking_failures"]

    def evidence(**metrics):
        payload = source_media_evidence(source_sha="a" * 64, pages=30, entries=1)
        payload["metrics"].update(metrics)
        return payload

    for override, blocker in [
        ({"unresolved_media": 1}, "source_media_integrity_failed"),
        ({"broken_provenance": 1}, "source_media_integrity_failed"),
        ({"missing_artifact": 1}, "source_media_integrity_failed"),
        ({"pages_scanned": 29}, "source_media_pass_incomplete"),
        ({"media_detected": 3}, "source_media_accounting_mismatch"),
    ]:
        result = _evaluate(annotations, source_media_evidence=evidence(**override))
        assert blocker in result["blocking_failures"], override
    stale = evidence()
    stale["source_media_pipeline_sha256"] = "0" * 64
    assert "source_media_evidence_stale_for_pipeline" in _evaluate(
        annotations, source_media_evidence=stale
    )["blocking_failures"]


def _packet(tmp_path):
    annotations, predictions, _ = _corpus()
    packet = tmp_path / "packet"
    (packet / "drafts").mkdir(parents=True)
    (packet / "media").mkdir()
    (packet / "page-images").mkdir()
    items = []
    for annotation, prediction in zip(annotations, predictions, strict=True):
        sample_id = annotation["sample_id"]
        (packet / "drafts" / f"{sample_id}.json").write_text(
            json.dumps(build_media_draft(annotation, prediction))
        )
        (packet / "page-images" / f"{sample_id}.png").write_bytes(b"page")
        media = []
        for item in prediction["media"]:
            name = f"media/{sample_id}-{item['media_order']:02d}.jpg"
            (packet / name).write_bytes(b"image")
            media.append({"media_order": item["media_order"], "file": name, "machine": item["machine"]})
        items.append(
            {
                "sample_id": sample_id,
                "page_number": annotation["page_number"],
                "page_image": f"page-images/{sample_id}.png",
                "draft": f"drafts/{sample_id}.json",
                "page_lemmas": ["word"],
                "media": media,
            }
        )
    (packet / "packet.json").write_text(json.dumps({"packet_version": "1.0", "items": items}))
    return annotations, predictions, packet


def test_human_media_review_requires_explicit_decisions_and_cannot_be_repeated(tmp_path):
    annotations, predictions, packet = _packet(tmp_path)
    target = tmp_path / "media_annotations"
    session = GoldMediaReviewSession(packet, target)
    assert session.list_pages()["human_verified_count"] == 0

    with pytest.raises(ValueError, match="checks are required"):
        session.verify_page(2, reviewer_id="r", checks=CHECKS[:2], decisions=[], notes=None)
    with pytest.raises(ValueError, match="every detected media item"):
        session.verify_page(2, reviewer_id="r", checks=CHECKS, decisions=[], notes=None)
    with pytest.raises(ValueError, match="reviewer_id is required"):
        session.verify_page(1, reviewer_id=" ", checks=CHECKS, decisions=[], notes=None)
    assert not list(target.glob("*.json"))

    session.verify_page(
        2,
        reviewer_id="reviewer-1",
        checks=CHECKS,
        decisions=[{"media_order": 1, "decision": "CORRECT_ASSOCIATION", "lemma": "fixed"}],
        notes="belongs to the entry above",
    )
    session.verify_page(
        5,
        reviewer_id="reviewer-1",
        checks=CHECKS,
        decisions=[
            {"media_order": 1, "decision": "APPROVE"},
            {"media_order": 2, "decision": "NOT_VOCABULARY_MEDIA"},
        ],
        notes=None,
    )
    session.verify_page(1, reviewer_id="reviewer-1", checks=CHECKS, decisions=[], notes=None)
    page_two = json.loads((target / "gold-v1-p0002.json").read_text())
    assert page_two["review_status"] == "HUMAN_VERIFIED"
    assert page_two["media"][0]["lemma"] == "fixed"
    assert page_two["media"][0]["human_decision"] == "CORRECT_ASSOCIATION"
    assert json.loads((target / "gold-v1-p0001.json").read_text())["media_count"] == 0
    with pytest.raises(ValueError, match="already HUMAN_VERIFIED"):
        session.verify_page(1, reviewer_id="other", checks=CHECKS, decisions=[], notes=None)

    session.report_missing_media(3, reviewer_id="reviewer-1", notes="illustration under entry x")
    page_three = json.loads((target / "gold-v1-p0003.json").read_text())
    assert (page_three["review_status"], page_three["missing_media_reported"]) == ("DRAFT", True)

    overlays = [json.loads(path.read_text()) for path in sorted(target.glob("*.json"))]
    report = evaluate_media_regression(annotations, overlays, predictions)
    assert report["status"] == "FAIL"  # 26 pages still unreviewed and one human correction
    assert report["metrics"]["gold_pages_checked"] == 3


def test_media_review_server_serves_packet_and_records_signoff(tmp_path):
    _, _, packet = _packet(tmp_path)
    text_packet = tmp_path / "text-packet"
    text_packet.mkdir()
    (text_packet / "packet.json").write_text(
        json.dumps({"items": [{"page_number": 1, "sample_id": "gold-v1-p0001"}]})
    )
    client = TestClient(
        create_gold_review_app(
            text_packet,
            tmp_path / "annotations",
            media_packet_dir=packet,
            media_annotations_dir=tmp_path / "media_annotations",
        )
    )
    assert "Source Media" in client.get("/media").text
    assert client.get("/api/media/state").json()["media_total"] == 3
    page = client.get("/api/media/pages/2").json()
    assert page["media"][0]["lemma"] == "word"
    assert client.get(page["media"][0]["content_url"]).content == b"image"
    assert client.get(page["image_url"]).content == b"page"
    rejected = client.post(
        "/api/media/pages/2/verify",
        json={"reviewer_id": "r", "checks": [], "decisions": []},
    )
    assert rejected.status_code == 409
    accepted = client.post(
        "/api/media/pages/2/verify",
        json={
            "reviewer_id": "reviewer-1",
            "checks": CHECKS,
            "decisions": [{"media_order": 1, "decision": "APPROVE"}],
        },
    )
    assert accepted.json()["review_status"] == "HUMAN_VERIFIED"
    assert client.get("/api/media/state").json()["human_verified_count"] == 1


def test_gate_cli_fails_closed_without_media_annotations(tmp_path, capsys):
    code = gate_main(
        [
            "--annotations",
            str(tmp_path / "missing"),
            "--media-annotations",
            str(tmp_path / "missing-media"),
            "--media-predictions",
            str(tmp_path / "missing-predictions"),
            "--require-pass",
        ]
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_release_gate_modules_import_without_application_dependencies():
    # The smoke script builds its evidence with the bare system interpreter.
    import subprocess
    import sys

    code = (
        "import sys; import app.production_smoke_evidence_cli; "
        "import app.services.release_readiness; "
        "sys.exit(any(name in sys.modules for name in ('sqlalchemy', 'fitz', 'fastapi')))"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
