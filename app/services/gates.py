from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import GateEvaluation, GoldRelease, Page, ProcessingRun, ProvenanceRecord, ReviewTask, SourceBlock, SourceEntry, SourceEntryBlock, VocabularyEntry


def _save_gate(db: Session, run: ProcessingRun, gate_name: str, status: str, metrics: dict, blocking: list, evidence: dict) -> dict:
    gate = db.query(GateEvaluation).filter(GateEvaluation.processing_run_id == run.id, GateEvaluation.gate == gate_name).one_or_none()
    if gate is None:
        gate = GateEvaluation(processing_run_id=run.id, gate=gate_name, ruleset_version="1.0.0", scope_type="DOCUMENT", scope_id=run.document_version_id, status=status, metrics=metrics, blocking_failures=blocking, evidence=evidence)
        db.add(gate)
    else:
        gate.status, gate.metrics, gate.blocking_failures, gate.evidence = status, metrics, blocking, evidence
    db.commit()
    return {"gate": gate_name, "status": status, "metrics": metrics, "blocking_failures": blocking}


def _run(db: Session, run_id: str) -> ProcessingRun:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    return run


def evaluate_g1_document_representation(db: Session, run_id: str) -> dict:
    run = _run(db, run_id)
    pages = db.query(Page).filter(Page.document_version_id == run.document_version_id).order_by(Page.page_number).all()
    blocks = db.query(SourceBlock).filter(SourceBlock.processing_run_id == run.id).all()
    represented = {b.page_id for b in blocks if b.raw_text}
    invalid = sum(1 for b in blocks if not _valid_bbox(b.bbox))
    metrics = {"page_count": len(pages), "represented_pages": sum(p.id in represented for p in pages), "text_block_count": len(blocks), "page_representation_coverage": sum(p.id in represented for p in pages) / len(pages) if pages else 0.0, "invalid_geometry_blocks": invalid, "silent_page_loss": sum(p.id not in represented for p in pages)}
    blocking = ([] if blocks else ["no_source_blocks"]) + (["invalid_geometry"] if invalid else []) + (["silent_page_loss"] if metrics["silent_page_loss"] else [])
    return _save_gate(db, run, "G1", "PASS" if not blocking else "FAIL", metrics, blocking, {"source_block_count": len(blocks)})


def _valid_bbox(bbox: dict) -> bool:
    try:
        if bbox.get("unit") != "normalized": return False
        x1, y1, x2, y2 = float(bbox["x1"]), float(bbox["y1"]), float(bbox["x2"]), float(bbox["y2"])
    except (KeyError, TypeError, ValueError): return False
    return 0.0 <= x1 <= x2 <= 1.0 and 0.0 <= y1 <= y2 <= 1.0


def evaluate_g2_entry_segmentation(db: Session, run_id: str) -> dict:
    run = _run(db, run_id)
    entries = db.query(SourceEntry).filter(SourceEntry.processing_run_id == run.id).all()
    links = db.query(SourceEntryBlock).join(SourceEntry, SourceEntry.id == SourceEntryBlock.source_entry_id).filter(SourceEntry.processing_run_id == run.id).all()
    linked = {x.source_entry_id for x in links}; empty = sum(not e.raw_text.strip() for e in entries); unlinked = sum(e.id not in linked for e in entries)
    metrics = {"source_entry_count": len(entries), "entry_block_link_count": len(links), "empty_entries": empty, "unlinked_entries": unlinked, "low_confidence_entries": sum(e.segmentation_confidence is None or e.segmentation_confidence < .5 for e in entries)}
    blocking = ([] if entries else ["no_source_entries"]) + (["empty_source_entries"] if empty else []) + (["unlinked_source_entries"] if unlinked else [])
    return _save_gate(db, run, "G2", "PASS" if not blocking else "FAIL", metrics, blocking, {"entry_block_links": len(links)})


def evaluate_g3_structured_extraction(db: Session, run_id: str) -> dict:
    run = _run(db, run_id); entries = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run.id).all()
    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.processing_run_id == run.id, ProvenanceRecord.target_entity_type == "VocabularyEntry", ProvenanceRecord.target_field_path == "lemma", ProvenanceRecord.provenance_type.like("SOURCE_%")).all(); proven = {p.target_entity_id for p in prov}
    missing = sum(not e.lemma.strip() for e in entries); missing_prov = sum(e.id not in proven for e in entries); review = sum(e.verification_status == "REVIEW_REQUIRED" for e in entries)
    metrics = {"vocabulary_entry_count": len(entries), "missing_lemma": missing, "missing_lemma_provenance": missing_prov, "review_required_entries": review}
    blocking = ([] if entries else ["no_vocabulary_entries"]) + (["missing_lemma"] if missing else []) + (["missing_required_provenance"] if missing_prov else [])
    return _save_gate(db, run, "G3", "FAIL" if blocking else ("REVIEW_REQUIRED" if review else "PASS"), metrics, blocking, {"lemma_provenance_records": len(prov)})


def evaluate_g4_validation(db: Session, run_id: str) -> dict:
    run = _run(db, run_id); entries = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run.id).all(); open_reviews = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run.id, ReviewTask.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"])).all()
    verified = sum(e.verification_status in {"AUTO_VERIFIED", "HUMAN_VERIFIED"} for e in entries); unresolved = len(entries) - verified
    metrics = {"vocabulary_entry_count": len(entries), "verified_entries": verified, "unresolved_entries": unresolved, "open_review_tasks": len(open_reviews)}; blocking = ([] if entries else ["no_vocabulary_entries"]) + (["unresolved_entries"] if unresolved else [])
    return _save_gate(db, run, "G4", "FAIL" if not entries else ("REVIEW_REQUIRED" if unresolved or open_reviews else "PASS"), metrics, blocking, {"open_review_task_ids": [t.id for t in open_reviews]})


def evaluate_g5_review_resolution(db: Session, run_id: str) -> dict:
    run = _run(db, run_id); tasks = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run.id).all(); open_tasks = [t for t in tasks if t.status in {"OPEN", "IN_PROGRESS", "ESCALATED"}]
    human = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run.id, VocabularyEntry.verification_status == "HUMAN_VERIFIED").count()
    metrics = {"review_task_count": len(tasks), "open_review_tasks": len(open_tasks), "resolved_review_tasks": sum(t.status == "RESOLVED" for t in tasks), "human_verified_entries": human}
    return _save_gate(db, run, "G5", "PASS" if not open_tasks else "REVIEW_REQUIRED", metrics, ["open_review_tasks"] if open_tasks else [], {"open_review_task_ids": [t.id for t in open_tasks]})


def evaluate_g6_gold_publication(db: Session, run_id: str) -> dict:
    run = _run(db, run_id); entries = db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run.id).all(); unresolved = [e.id for e in entries if e.verification_status not in {"AUTO_VERIFIED", "HUMAN_VERIFIED"}]
    open_reviews = db.query(ReviewTask).filter(ReviewTask.processing_run_id == run.id, ReviewTask.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"])).count(); releases = db.query(GoldRelease).filter(GoldRelease.processing_run_id == run.id).count()
    metrics = {"vocabulary_entry_count": len(entries), "unresolved_entries": len(unresolved), "open_review_tasks": open_reviews, "gold_release_count": releases}; blocking = ([] if entries else ["no_vocabulary_entries"]) + (["unresolved_entries"] if unresolved else []) + (["open_review_tasks"] if open_reviews else [])
    return _save_gate(db, run, "G6", "PASS" if not blocking else "FAIL", metrics, blocking, {"gold_release_count": releases})
