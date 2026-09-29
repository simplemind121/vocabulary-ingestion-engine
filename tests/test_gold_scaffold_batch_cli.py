from __future__ import annotations

import json
import sys

import pytest

from app.cli import gold_scaffold_batch


def _assets() -> tuple[dict[str, object], dict[str, object]]:
    source_sha = "a" * 64
    candidates = [
        {"pdf_page": page, "tags": ["dense"]}
        for page in range(1, 31)
    ]
    plan = {
        "source_document_sha256": source_sha,
        "candidates": candidates,
    }
    hashes = {
        "source_document_sha256": source_sha,
        "pages": {str(page): f"{page:064x}" for page in range(1, 31)},
    }
    return plan, hashes


def test_cli_builds_frozen_30_page_scaffold_artifact(tmp_path, monkeypatch):
    plan, hashes = _assets()
    plan_path = tmp_path / "selection.json"
    hashes_path = tmp_path / "hashes.json"
    output_path = tmp_path / "scaffolds.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    hashes_path.write_text(json.dumps(hashes), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gold-scaffold-batch",
            "--selection-plan",
            str(plan_path),
            "--page-hashes",
            str(hashes_path),
            "--output",
            str(output_path),
        ],
    )

    assert gold_scaffold_batch.main() == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(payload) == 30
    assert [item["page_number"] for item in payload] == list(range(1, 31))
    assert all(item["review_status"] == "DRAFT" for item in payload)
    assert all(item["reviewer_id"] is None for item in payload)
    assert all(len(item["page_image_sha256"]) == 64 for item in payload)


def test_cli_fails_closed_without_output_on_identity_mismatch(tmp_path, monkeypatch):
    plan, hashes = _assets()
    hashes["source_document_sha256"] = "b" * 64
    plan_path = tmp_path / "selection.json"
    hashes_path = tmp_path / "hashes.json"
    output_path = tmp_path / "scaffolds.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    hashes_path.write_text(json.dumps(hashes), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gold-scaffold-batch",
            "--selection-plan",
            str(plan_path),
            "--page-hashes",
            str(hashes_path),
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(ValueError, match="source_document_sha256_mismatch"):
        gold_scaffold_batch.main()
    assert not output_path.exists()
    assert not (tmp_path / ".scaffolds.json.tmp").exists()
