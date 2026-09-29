import json
from pathlib import Path

from app.services.gold_page_hashes import validate_page_hash_registry

GOLD_DIR = Path(__file__).parents[1] / "gold_samples"


def _load(name: str) -> dict:
    return json.loads((GOLD_DIR / name).read_text(encoding="utf-8"))


def test_repository_hash_registry_exactly_covers_selection_plan() -> None:
    result = validate_page_hash_registry(
        _load("page_image_hashes_v1.json"),
        selection_plan=_load("selection_plan_v1.json"),
    )

    assert result == {
        "status": "PASS",
        "selected_page_count": 30,
        "hashed_page_count": 30,
        "errors": [],
    }


def test_missing_selected_page_hash_fails_closed() -> None:
    registry = _load("page_image_hashes_v1.json")
    plan = _load("selection_plan_v1.json")
    registry["pages"].pop(str(plan["candidates"][0]["pdf_page"]))

    result = validate_page_hash_registry(registry, selection_plan=plan)

    assert result["status"] == "FAIL"
    assert any("missing page hashes" in error for error in result["errors"])


def test_render_contract_drift_fails_closed() -> None:
    registry = _load("page_image_hashes_v1.json")
    registry["render_contract"]["dpi"] = 300

    result = validate_page_hash_registry(
        registry,
        selection_plan=_load("selection_plan_v1.json"),
    )

    assert result["status"] == "FAIL"
    assert "render contract does not match frozen Gold Sample render contract" in result["errors"]


def test_source_digest_mismatch_fails_closed() -> None:
    registry = _load("page_image_hashes_v1.json")
    registry["source_document_sha256"] = "0" * 64

    result = validate_page_hash_registry(
        registry,
        selection_plan=_load("selection_plan_v1.json"),
    )

    assert result["status"] == "FAIL"
    assert "source document SHA256 does not match selection plan" in result["errors"]
