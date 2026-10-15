from __future__ import annotations

import fitz
from sqlalchemy.orm import Session

from app.models import Artifact, DocumentVersion, ProcessingRun

_MIN_NATIVE_CHARS_PER_PAGE = 20
# Text drawn invisibly over a page image is a scanner's OCR, not the book's own text.
_HIDDEN_SHARE = 0.9
_INVISIBLE = 3


def _hidden_share(page) -> float:
    """How much of a page's text is drawn invisibly (PDF text render mode 3)."""
    total = hidden = 0
    for span in page.get_texttrace():
        count = len(span.get("chars") or ())
        total += count
        if span.get("type") == _INVISIBLE:
            hidden += count
    return hidden / total if total else 0.0


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
            hidden = char_count >= _MIN_NATIVE_CHARS_PER_PAGE and _hidden_share(page) >= _HIDDEN_SHARE
            page_stats.append(
                {
                    "page_number": page_number,
                    "native_char_count": char_count,
                    # A hidden OCR layer is read again (and voted on), not trusted.
                    "has_meaningful_native_text": char_count >= _MIN_NATIVE_CHARS_PER_PAGE and not hidden,
                    "hidden_text_layer": hidden,
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
        "hidden_text_layer_pages": sum(1 for page in page_stats if page["hidden_text_layer"]),
        "pages": page_stats,
    }
