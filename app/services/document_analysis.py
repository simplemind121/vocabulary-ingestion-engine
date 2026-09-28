from __future__ import annotations

import fitz
from sqlalchemy.orm import Session

from app.models import Artifact, DocumentVersion, ProcessingRun

_MIN_NATIVE_CHARS_PER_PAGE = 20


def analyze_text_layer(db: Session, run_id: str) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")

    version = db.get(DocumentVersion, run.document_version_id)
    if version is None:
        raise ValueError("document version not found")

    artifact = db.get(Artifact, version.source_artifact_id)
    if artifact is None:
        raise ValueError("source artifact not found")

    pdf = fitz.open(artifact.object_key)
    page_stats: list[dict] = []
    try:
        for page_number, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()
            char_count = len(text)
            page_stats.append(
                {
                    "page_number": page_number,
                    "native_char_count": char_count,
                    "has_meaningful_native_text": char_count >= _MIN_NATIVE_CHARS_PER_PAGE,
                }
            )
    finally:
        pdf.close()

    meaningful_pages = sum(1 for page in page_stats if page["has_meaningful_native_text"])
    total_pages = len(page_stats)
    native_ratio = meaningful_pages / total_pages if total_pages else 0.0
    if total_pages == 0:
        document_mode = "INVALID"
    elif native_ratio == 1.0:
        document_mode = "NATIVE_TEXT"
    elif native_ratio == 0.0:
        document_mode = "SCANNED"
    else:
        document_mode = "HYBRID"

    return {
        "run_id": run_id,
        "document_mode": document_mode,
        "page_count": total_pages,
        "native_text_pages": meaningful_pages,
        "native_text_page_ratio": native_ratio,
        "pages": page_stats,
    }
