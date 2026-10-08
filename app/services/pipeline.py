from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.ocr_base import OcrEngineAdapter
from app.models import ProcessingRun
from app.services.document_analysis import analyze_text_layer
from app.services.extraction import extract_native_blocks
from app.services.gates import (
    evaluate_g1_document_representation,
    evaluate_g2_entry_segmentation,
    evaluate_g3_structured_extraction,
    evaluate_g4_validation,
    evaluate_g5_review_resolution,
    evaluate_g6_gold_publication,
    evaluate_source_media_gate,
)
from app.services.gold import publish_gold_release
from app.services.ocr_extraction import extract_ocr_blocks
from app.services.ocr_quality import route_ocr_quality_reviews
from app.services.page_checklist import apply_headword_checklists
from app.services.page_quality import route_no_text_page_reviews
from app.services.segmentation import segment_source_entries
from app.services.source_media import extract_source_media
from app.services.structured_extraction import extract_canonical_fields
from app.services.validation import validate_canonical_entries


class PipelineBlocked(RuntimeError):
    def __init__(self, gate: str, result: dict):
        super().__init__(f"pipeline blocked at {gate}: {result['status']}")
        self.gate = gate
        self.result = result


def run_pipeline(
    db: Session,
    run_id: str,
    *,
    publish: bool = True,
    ocr_adapter: OcrEngineAdapter | None = None,
    ocr_min_confidence: float = 0.85,
    ocr_page_workers: int = 1,
    ocr_adapter_factory: Callable[[], OcrEngineAdapter] | None = None,
) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")

    run.status = "RUNNING"
    run.finished_at = None
    db.commit()
    stages: list[dict] = []

    try:
        analysis = analyze_text_layer(db, run_id)
        stages.append({"stage": "document_analysis", "result": analysis})
        document_mode = analysis["document_mode"]

        if document_mode == "NATIVE_TEXT":
            extraction = extract_native_blocks(db, run_id)
            stages.append({"stage": "native_extraction", "result": extraction})
        elif document_mode == "HYBRID":
            native_pages = {
                page["page_number"]
                for page in analysis["pages"]
                if page["has_meaningful_native_text"]
            }
            ocr_pages = {
                page["page_number"]
                for page in analysis["pages"]
                if not page["has_meaningful_native_text"]
            }
            if ocr_adapter is None:
                native = extract_native_blocks(db, run_id, page_numbers=native_pages)
                stages.append({"stage": "native_extraction", "result": native})
                page_reviews = route_no_text_page_reviews(
                    db,
                    run_id,
                    page_numbers=ocr_pages,
                )
                stages.append({"stage": "no_text_page_review", "result": page_reviews})
                _require_pass("G1", evaluate_g1_document_representation(db, run_id), stages)
                raise AssertionError("G1 must require review for unresolved no-text pages")
            native = extract_native_blocks(db, run_id, page_numbers=native_pages)
            stages.append({"stage": "native_extraction", "result": native})
            ocr = extract_ocr_blocks(
                db,
                run_id,
                ocr_adapter,
                page_numbers=ocr_pages,
                page_workers=ocr_page_workers,
                adapter_factory=ocr_adapter_factory,
            )
            stages.append({"stage": "ocr_extraction", "result": ocr})
            checklists = apply_headword_checklists(db, run_id)
            stages.append({"stage": "headword_checklists", "result": checklists})
            quality = route_ocr_quality_reviews(
                db,
                run_id,
                min_confidence=ocr_min_confidence,
            )
            stages.append({"stage": "ocr_quality", "result": quality})
        elif ocr_adapter is not None:
            extraction = extract_ocr_blocks(
                db,
                run_id,
                ocr_adapter,
                page_workers=ocr_page_workers,
                adapter_factory=ocr_adapter_factory,
            )
            stages.append({"stage": "ocr_extraction", "result": extraction})
            checklists = apply_headword_checklists(db, run_id)
            stages.append({"stage": "headword_checklists", "result": checklists})
            quality = route_ocr_quality_reviews(
                db,
                run_id,
                min_confidence=ocr_min_confidence,
            )
            stages.append({"stage": "ocr_quality", "result": quality})
        else:
            return _ocr_required(db, run, document_mode, stages)

        _require_pass("G1", evaluate_g1_document_representation(db, run_id), stages)
        segmentation = segment_source_entries(db, run_id)
        stages.append({"stage": "entry_segmentation", "result": segmentation})
        _require_pass("G2", evaluate_g2_entry_segmentation(db, run_id), stages)
        structured = extract_canonical_fields(db, run_id)
        stages.append({"stage": "structured_extraction", "result": structured})
        _require_pass("G3", evaluate_g3_structured_extraction(db, run_id), stages)
        media = extract_source_media(db, run_id)
        stages.append({"stage": "source_media", "result": media})
        media_gate = evaluate_source_media_gate(db, run_id)
        stages.append({"stage": "G3_MEDIA", "result": media_gate})
        if media_gate["status"] == "FAIL":
            raise PipelineBlocked("G3_MEDIA", media_gate)
        validation = validate_canonical_entries(db, run_id)
        stages.append({"stage": "validation", "result": validation})
        g4 = evaluate_g4_validation(db, run_id)
        stages.append({"stage": "G4", "result": g4})
        if g4["status"] == "FAIL":
            raise PipelineBlocked("G4", g4)
        _require_pass("G5", evaluate_g5_review_resolution(db, run_id), stages)
        _require_pass("G3_MEDIA", evaluate_source_media_gate(db, run_id), stages)
        _require_pass("G6", evaluate_g6_gold_publication(db, run_id), stages)

        release = publish_gold_release(db, run_id) if publish else None
        run.status = "COMPLETED"
        run.finished_at = datetime.now(UTC)
        run.metrics = {
            **(run.metrics or {}),
            "pipeline_stages": len(stages),
            "gold_release_id": release.id if release else None,
        }
        db.commit()
        return {
            "run_id": run_id,
            "status": run.status,
            "stages": stages,
            "gold_release_id": release.id if release else None,
        }
    except PipelineBlocked as exc:
        run.status = "REVIEW_REQUIRED" if exc.result["status"] == "REVIEW_REQUIRED" else "FAILED"
        run.finished_at = datetime.now(UTC)
        run.error_summary = {"blocked_gate": exc.gate, "gate_result": exc.result}
        db.commit()
        return {
            "run_id": run_id,
            "status": run.status,
            "blocked_gate": exc.gate,
            "gate_result": exc.result,
            "stages": stages,
        }
    except Exception as exc:
        # A failed flush leaves the session unusable; without this the run
        # would stay RUNNING forever and could never be queued again.
        db.rollback()
        run = db.get(ProcessingRun, run_id)
        run.status = "FAILED"
        run.finished_at = datetime.now(UTC)
        run.error_summary = {"error_type": type(exc).__name__, "message": str(exc)}
        db.commit()
        raise


def _ocr_required(db: Session, run: ProcessingRun, document_mode: str, stages: list[dict]) -> dict:
    run.status = "OCR_REQUIRED"
    run.finished_at = datetime.now(UTC)
    run.error_summary = {
        "blocked_stage": "document_analysis",
        "reason": "ocr_adapter_not_configured",
        "document_mode": document_mode,
    }
    db.commit()
    return {
        "run_id": run.id,
        "status": run.status,
        "blocked_stage": "document_analysis",
        "reason": "ocr_adapter_not_configured",
        "document_mode": document_mode,
        "stages": stages,
    }


def _require_pass(gate: str, result: dict, stages: list[dict]) -> None:
    stages.append({"stage": gate, "result": result})
    if result["status"] != "PASS":
        raise PipelineBlocked(gate, result)
