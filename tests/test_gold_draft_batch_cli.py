from __future__ import annotations

import json
import sys

from app.cli import gold_draft_batch


def test_gold_draft_batch_cli_writes_machine_drafts_atomically(tmp_path, monkeypatch):
    scaffolds_path = tmp_path / "scaffolds.json"
    output_path = tmp_path / "drafts.json"
    scaffolds = [{"page_number": page, "review_status": "DRAFT"} for page in range(1, 31)]
    scaffolds_path.write_text(json.dumps(scaffolds), encoding="utf-8")

    captured = {}

    def fake_build(db, run_id, received, *, generator):
        captured.update(run_id=run_id, scaffolds=received, generator=generator)
        return [
            {
                "page_number": item["page_number"],
                "review_status": "DRAFT",
                "reviewer_id": None,
            }
            for item in received
        ]

    monkeypatch.setattr(gold_draft_batch, "build_gold_draft_batch_from_run", fake_build)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gold-draft-batch",
            "--run-id",
            "run-123",
            "--scaffolds",
            str(scaffolds_path),
            "--output",
            str(output_path),
            "--generator",
            "vie-test",
        ],
    )

    assert gold_draft_batch.main() == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(payload) == 30
    assert all(item["review_status"] == "DRAFT" for item in payload)
    assert all(item["reviewer_id"] is None for item in payload)
    assert captured == {
        "run_id": "run-123",
        "scaffolds": scaffolds,
        "generator": "vie-test",
    }
    assert not (tmp_path / ".drafts.json.tmp").exists()


def test_gold_draft_batch_cli_does_not_publish_partial_output_on_failure(
    tmp_path, monkeypatch
):
    scaffolds_path = tmp_path / "scaffolds.json"
    output_path = tmp_path / "drafts.json"
    scaffolds_path.write_text(
        json.dumps([{"page_number": page, "review_status": "DRAFT"} for page in range(1, 31)]),
        encoding="utf-8",
    )

    def fail_closed(*args, **kwargs):
        raise ValueError("page_identity_mismatch")

    monkeypatch.setattr(gold_draft_batch, "build_gold_draft_batch_from_run", fail_closed)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gold-draft-batch",
            "--run-id",
            "run-123",
            "--scaffolds",
            str(scaffolds_path),
            "--output",
            str(output_path),
            "--generator",
            "vie-test",
        ],
    )

    try:
        gold_draft_batch.main()
    except ValueError as exc:
        assert str(exc) == "page_identity_mismatch"
    else:
        raise AssertionError("expected fail-closed Gold batch error")

    assert not output_path.exists()
    assert not (tmp_path / ".drafts.json.tmp").exists()
