"""Shared builders for Source Media Gold fixtures."""

from pathlib import Path

from app.services.full_book_evidence import source_media_pipeline_sha256
from app.services.gold_media import build_media_draft

ROOT = Path(__file__).resolve().parents[1]


def media_item(order: int, *, lemma: str | None, seed: int) -> dict:
    return {
        "media_order": order,
        "sha256": f"{seed:064x}",
        "bbox": {"x1": 0.4, "y1": 0.2, "x2": 0.6, "y2": 0.4, "unit": "normalized"},
        "width": 100,
        "height": 100,
        "mime_type": "image/jpeg",
        "media_role": "ENTRY_ILLUSTRATION" if lemma else "NON_VOCABULARY",
        "lemma": lemma,
        "machine": {"verification_status": "AUTO_VERIFIED", "confidence": 0.98, "warnings": []},
    }


def media_predictions(annotations: list[dict], media_by_page: dict[int, list[dict]]) -> list[dict]:
    return [
        {
            "sample_id": item["sample_id"],
            "document_sha256": item["document_sha256"],
            "page_number": item["page_number"],
            "processing_run_id": "run",
            "media": media_by_page.get(item["page_number"], []),
        }
        for item in annotations
    ]


def verified_media_overlays(annotations: list[dict], predictions: list[dict]) -> list[dict]:
    overlays = []
    for annotation, prediction in zip(annotations, predictions, strict=True):
        overlay = build_media_draft(annotation, prediction)
        for item in overlay["media"]:
            item["human_decision"] = "APPROVE"
        overlay.update(
            {"review_status": "HUMAN_VERIFIED", "reviewer_id": "human-reviewer", "review_notes": []}
        )
        overlays.append(overlay)
    return overlays


def source_media_evidence(*, source_sha: str, pages: int, entries: int, media: int = 2) -> dict:
    return {
        "evidence_schema_version": "1.0",
        "source_document_sha256": source_sha,
        "processing_run_id": "run",
        "source_media_pipeline_sha256": source_media_pipeline_sha256(ROOT),
        "vocabulary_entry_count": entries,
        "metrics": {
            "total_pages": pages,
            "pages_scanned": pages,
            "media_detected": media,
            "media_extracted": media,
            "media_persisted": media,
            "missing_media": 0,
            "unresolved_media": 0,
            "unbound_media": 0,
            "missing_artifact": 0,
            "missing_sha256": 0,
            "broken_artifact": 0,
            "broken_provenance": 0,
            "open_media_reviews": 0,
        },
        "media": [{"page": index + 1, "sha256": f"{index + 1:064x}"} for index in range(media)],
        "copyrighted_media_included": False,
    }
