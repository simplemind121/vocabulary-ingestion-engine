from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    GateEvaluation,
    Page,
    ProcessingRun,
    ProvenanceRecord,
    ReviewTask,
    SourceBlock,
    SourceEntry,
    SourceEntryBlock,
    VocabularyEntry,
)


def _save_gate(db: Session, run: ProcessingRun, gate_name: str, status: str, metrics: dict, blocking: list, evidence: dict) -> dict:
    gate = db.query(GateEvaluation).filter(GateEvaluation.processing_run_id == run.id, GateEvaluation.gate == gate_name).one_or_none()
    if gate is None:
        gate = GateEvaluation(processing_run_id=run.id, gate=gate_name, ruleset_version="1.0.0", scope_type="DOCUMENT", scope_id=run.document_version_id, status=status, metrics=metrics, blocking_failures=blocking, evidence=evidence)
        db.add(gate)
    else:
        gate.status = status
        gate.metrics = metrics
        gate.blocking_failures = blocking
        gate.evidence = evidence
    db.commit()
    return {"gate": gate_name, "status": status, "metrics": metrics, "blocking_failures": blocking}


def evaluate_g1_document_representation(db: Session, run_id: str) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    pages = db.query(Page).filter(Page.document_version_id == run.document_version_id).order_by(Page.page_number).all()
    blocks = db.query(SourceBlock).filter(SourceBlock.processing_run_id == run.id).all()
    page_ids_with_blocks = {block.page_id for block in blocks if block.raw_text}
    represented_pages = sum(1 for page in pages if page.id in page_ids_with_blocks)
    coverage = represented_pages / len(pages) if pages else 0.0
    invalid_geometry = sum(1 for block in blocks if not _valid_bbox(block.bbox))
    metrics = {"page_count": len(pages), "represented_pages": represented_pages, "text_block_count": len(blocks), "page_representation_coverage": coverage, "invalid_geometry_blocks": invalid_geometry, "silent_page_loss": max(len(pages) - represented_pages, 0)}
    blocking = []
    if not blocks:
        blocking.append("no_source_blocks")
    if invalid_geometry:
        blocking.append("invalid_geometry")
    if represented_pages != len(pages):
        blocking.append("silent_page_loss")
    return _save_gate(db, run, "G1", "PASS" if not blocking else "FAIL", metrics, blocking, {"source_block_count": len(blocks)})


def _valid_bbox(bbox: dict) -> bool:
    try:
        if bbox.get("unit") != "normalized":
            return False
        x1, y1, x2, y2 = float(bbox["x1"]), float(bbox["y1"]), float(bbox["x2"]), float(bbox["y2"])
    except (KeyError, TypeError, ValueError):
        return False
    return 0.0 <= x1 <= x2 <= 1.0 and 0.0 <= y1 <= y2 <= 1.0


def evaluate_g2_entry_segmentation(db: Session, run_id: str) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    entries = db.query(SourceEntry).filter(SourceEntry.processing_run_id == run.id).order_by(SourceEntry.entry_order).all()
    links = db.query(SourceEntryBlock).join(SourceEntry, SourceEntry.id == SourceEntryBlock.source_entry_id).filter(SourceEntry.processing_run_id == run.id).all()
    linked_entry_ids = {link.source_entry_id for link in links}
    empty_entries = sum(1 for entry in entries if not entry.raw_text.strip())
    unlinked_entries = sum(1 for entry in entries if entry.id not in linked_entry_ids)
    low_confidence_entries = sum(1 for entry in entries if entry.segmentation_confidence is None or entry.segmentation_confidence < 0.50)
    metrics = {"source_entry_count": len(entries), "entry_block_link_count": len(links), "empty_entries": empty_entries, "unlinked_entries": unlinked_entries, "low_confidence_entries": low_confidence_entries}
    blocking = []
    if not entries:
        blocking.append("no_source_entries")
    if empty_entries:
        blocking.append("empty_source_entries")
    if unlinked_entries:
        blocking.append("unlinked_source_entries")
    return _save_gate(db, run, "G2", "PASS" if not blocking else "FAIL", metrics, blocking, {"entry_block_links": len(links)})


def evaluate_g3_structured_extraction(db: Session, run_id: str) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    entries = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run.id).all()
    lemma_provenance = db.query(ProvenanceRecord).filter(ProvenanceRecord.processing_run_id == run.id, ProvenanceRecord.target_entity_type == "VocabularyEntry", ProvenanceRecord.target_field_path == "lemma", ProvenanceRecord.provenance_type.like("SOURCE_%")).all()
    proven_entry_ids = {record.target_entity_id for record in lemma_provenance}
    missing_lemma = sum(1 for entry in entries if not entry.lemma.strip())
    missing_lemma_provenance = sum(1 for entry in entries if entry.id not in proven_entry_ids)
    review_required = sum(1 for entry in entries if entry.verification_status == "REVIEW_REQUIRED")
    metrics = {"vocabulary_entry_count": len(entries), "missing_lemma": missing_lemma, "missing_lemma_provenance": missing_lemma_provenance, "review_required_entries": review_required}
    blocking = []
    if not entries:
        blocking.append("no_vocabulary_entries")
    if missing_lemma:
        blocking.append("missing_lemma")
    if missing_lemma_provenance:
        blocking.append("missing_required_provenance")
    status = "FAIL" if blocking else ("REVIEW_REQUIRED" if review_required else "PASS")
    return _save_gate(db, run, "G3", status, metrics, blocking, {"lemma_provenance_records": len(lemma_provenance)})


def evaluate_g4_validation(db: Session, run_id: str) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    entries = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run.id).all()
    open_reviews = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run.id, ReviewTask.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"])).all()
    verified = sum(1 for entry in entries if entry.verification_status in {"AUTO_VERIFIED", "HUMAN_VERIFIED"})
    unresolved = sum(1 for entry in entries if entry.verification_status not in {"AUTO_VERIFIED", "HUMAN_VERIFIED"})
    metrics = {"vocabulary_entry_count": len(entries), "verified_entries": verified, "unresolved_entries": unresolved, "open_review_tasks": len(open_reviews)}
    blocking = []
    if not entries:
        blocking.append("no_vocabulary_entries")
    if unresolved:
        blocking.append("unresolved_entries")
    status = "FAIL" if not entries else ("REVIEW_REQUIRED" if unresolved or open_reviews else "PASS")
    return _save_gate(db, run, "G4", status, metrics, blocking, {"open_review_task_ids": [task.id for task in open_reviews]})
