from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import ProcessingRun
from app.services.extraction import extract_native_blocks
from app.services.gates import (
    evaluate_g1_document_representation,
    evaluate_g2_entry_segmentation,
    evaluate_g3_structured_extraction,
    evaluate_g4_validation,
    evaluate_g5_review_resolution,
    evaluate_g6_gold_publication,
)
from app.services.gold import publish_gold_release
from app.services.segmentation import segment_source_entries
from app.services.structured_extraction import extract_canonical_fields
from app.services.validation import validate_canonical_entries


class PipelineBlocked(RuntimeError):
    def __init__(self, gate: str, result: dict):
        super().__init__(f"pipeline blocked at {gate}: {result['status']}")
        self.gate = gate
        self.result = result


def run_pipeline(db: Session, run_id: str, *, publish: bool = True) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")

    run.status = "RUNNING"
    run.finished_at = None
    db.commit()
    stages: list[dict] = []

    try:
        extraction = extract_native_blocks(db, run_id)
        stages.append({"stage": "native_extraction", "result": extraction})
        _require_pass("G1", evaluate_g1_document_representation(db, run_id), stages)

        segmentation = segment_source_entries(db, run_id)
        stages.append({"stage": "entry_segmentation", "result": segmentation})
        _require_pass("G2", evaluate_g2_entry_segmentation(db, run_id), stages)

        structured = extract_canonical_fields(db, run_id)
        stages.append({"stage": "structured_extraction", "result": structured})
        _require_pass("G3", evaluate_g3_structured_extraction(db, run_id), stages)

        validation = validate_canonical_entries(db, run_id)
        stages.append({"stage": "validation", "result": validation})
        _require_pass("G4", evaluate_g4_validation(db, run_id), stages)
        _require_pass("G5", evaluate_g5_review_resolution(db, run_id), stages)
        _require_pass("G6", evaluate_g6_gold_publication(db, run_id), stages)

        release = publish_gold_release(db, run_id) if publish else None
        run.status = "COMPLETED"
        run.finished_at = datetime.now(UTC)
        run.metrics = {**(run.metrics or {}), "pipeline_stages": len(stages), "gold_release_id": release.id if release else None}
        db.commit()
        return {"run_id": run_id, "status": run.status, "stages": stages, "gold_release_id": release.id if release else None}
    except PipelineBlocked as exc:
        run.status = "REVIEW_REQUIRED" if exc.result["status"] == "REVIEW_REQUIRED" else "FAILED"
        run.finished_at = datetime.now(UTC)
        run.error_summary = {"blocked_gate": exc.gate, "gate_result": exc.result}
        db.commit()
        return {"run_id": run_id, "status": run.status, "blocked_gate": exc.gate, "gate_result": exc.result, "stages": stages}
    except Exception as exc:
        run.status = "FAILED"
        run.finished_at = datetime.now(UTC)
        run.error_summary = {"error_type": type(exc).__name__, "message": str(exc)}
        db.commit()
        raise


def _require_pass(gate: str, result: dict, stages: list[dict]) -> None:
    stages.append({"stage": gate, "result": result})
    if result["status"] != "PASS":
        raise PipelineBlocked(gate, result)
