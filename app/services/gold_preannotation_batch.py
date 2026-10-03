from __future__ import annotations

from typing import Any

from app.services.gold_preannotation import build_machine_annotation_draft


def build_machine_annotation_batch(
    scaffolds: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    *,
    generator: str,
) -> list[dict[str, Any]]:
    """Join machine predictions to frozen Gold scaffolds without changing review status.

    Predictions must identify the exact source document, page and rendered-page hash.
    The join is deliberately fail-closed: missing, duplicate, extra or identity-drifted
    predictions abort the entire batch rather than producing a partial Gold draft set.
    """
    if not isinstance(generator, str) or not generator.strip():
        raise ValueError("generator_required")
    if len(scaffolds) != 30:
        raise ValueError("gold_sample_requires_exactly_30_scaffolds")
    if len(predictions) != 30:
        raise ValueError("gold_sample_requires_exactly_30_predictions")

    scaffold_by_page: dict[int, dict[str, Any]] = {}
    for scaffold in scaffolds:
        page = scaffold.get("page_number")
        if not isinstance(page, int) or page in scaffold_by_page:
            raise ValueError("scaffold_pages_must_be_unique_integers")
        if scaffold.get("review_status") != "DRAFT":
            raise ValueError(f"scaffold_must_be_draft:{page}")
        scaffold_by_page[page] = scaffold

    prediction_by_page: dict[int, dict[str, Any]] = {}
    for prediction in predictions:
        page = prediction.get("page_number")
        if not isinstance(page, int) or page in prediction_by_page:
            raise ValueError("prediction_pages_must_be_unique_integers")
        prediction_by_page[page] = prediction

    if set(scaffold_by_page) != set(prediction_by_page):
        raise ValueError("prediction_pages_must_match_scaffolds")

    drafts: list[dict[str, Any]] = []
    for page in sorted(scaffold_by_page):
        scaffold = scaffold_by_page[page]
        prediction = prediction_by_page[page]
        _require_identity_match(scaffold, prediction, page=page)
        drafts.append(
            build_machine_annotation_draft(
                scaffold,
                prediction,
                generator=generator.strip(),
            )
        )
    return drafts


def _require_identity_match(
    scaffold: dict[str, Any],
    prediction: dict[str, Any],
    *,
    page: int,
) -> None:
    for field in ("document_sha256", "page_image_sha256"):
        if prediction.get(field) != scaffold.get(field):
            raise ValueError(f"prediction_identity_mismatch:{page}:{field}")
