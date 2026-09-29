import json
from pathlib import Path

from app.services.gold_selection_plan import validate_selection_plan


def test_repository_selection_plan_is_internally_consistent() -> None:
    plan = json.loads(Path("gold_samples/selection_plan_v1.json").read_text(encoding="utf-8"))

    result = validate_selection_plan(plan, source_page_count=1120)

    assert result == {
        "status": "PASS",
        "candidate_count": 17,
        "remaining_slots": 13,
        "errors": [],
    }


def test_selection_plan_rejects_duplicate_and_out_of_range_pages() -> None:
    plan = {
        "selection_status": "CANDIDATE_SELECTION",
        "candidates": [
            {"pdf_page": 1, "tags": ["NORMAL"], "reason": "candidate"},
            {"pdf_page": 1, "tags": ["NORMAL"], "reason": "duplicate"},
            {"pdf_page": 1121, "tags": ["NORMAL"], "reason": "outside"},
        ],
        "remaining_slots": 27,
    }

    result = validate_selection_plan(plan, source_page_count=1120)

    assert result["status"] == "FAIL"
    assert "candidate pdf_page values must be unique" in result["errors"]
    assert "candidate[2].pdf_page is outside source document" in result["errors"]


def test_semantic_boundary_tags_require_direct_inspection_evidence() -> None:
    plan = {
        "selection_status": "CANDIDATE_SELECTION",
        "candidates": [
            {
                "pdf_page": 220,
                "tags": ["NORMAL", "CROSS_PAGE_ENTRY"],
                "reason": "automatic profiler inferred a page boundary",
            }
        ],
        "remaining_slots": 29,
    }

    result = validate_selection_plan(plan, source_page_count=1120)

    assert result["status"] == "FAIL"
    assert any("direct-inspection evidence" in error for error in result["errors"])


def test_selection_plan_cannot_claim_verified_status() -> None:
    plan = {
        "selection_status": "HUMAN_VERIFIED",
        "candidates": [],
        "remaining_slots": 30,
    }

    result = validate_selection_plan(plan, source_page_count=1120)

    assert result["status"] == "FAIL"
    assert "selection_status must be CANDIDATE_SELECTION" in result["errors"]
