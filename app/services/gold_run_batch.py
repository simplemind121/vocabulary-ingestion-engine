from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.gold_preannotation_batch import build_machine_annotation_batch
from app.services.gold_prediction_adapter import build_gold_prediction_from_run


def build_gold_prediction_batch_from_run(
    db: Session,
    run_id: str,
    scaffolds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the complete 30-page prediction set from one persisted processing run.

    The existing per-page adapter remains the identity/provenance authority. This
    orchestration layer only accepts the frozen 30-page Gold sample and aborts the
    whole batch if any page cannot be reconstructed from the run.
    """
    if len(scaffolds) != 30:
        raise ValueError("gold_sample_requires_exactly_30_scaffolds")

    pages: set[int] = set()
    for scaffold in scaffolds:
        page = scaffold.get("page_number")
        if not isinstance(page, int) or page in pages:
            raise ValueError("scaffold_pages_must_be_unique_integers")
        if scaffold.get("review_status") != "DRAFT":
            raise ValueError(f"scaffold_must_be_draft:{page}")
        pages.add(page)

    return [
        build_gold_prediction_from_run(db, run_id, scaffold)
        for scaffold in sorted(scaffolds, key=lambda item: item["page_number"])
    ]


def build_gold_draft_batch_from_run(
    db: Session,
    run_id: str,
    scaffolds: list[dict[str, Any]],
    *,
    generator: str,
) -> list[dict[str, Any]]:
    """Produce 30 machine DRAFT annotations from persisted pipeline output."""
    predictions = build_gold_prediction_batch_from_run(db, run_id, scaffolds)
    return build_machine_annotation_batch(
        scaffolds,
        predictions,
        generator=generator,
    )
