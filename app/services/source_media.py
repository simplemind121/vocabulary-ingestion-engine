"""Source media: illustrations printed in the original book.

SOURCE_MEDIA is source data. It is extracted byte-for-byte from the PDF, hashed,
stored through the object storage abstraction, and bound to the entry it
illustrates by page geometry alone. Anything the geometry cannot prove goes to
the Review Queue; nothing here guesses. AI-generated imagery is a different
namespace (ENRICHMENT_MEDIA) and never passes through this module.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import fitz
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.orm import Session

from app.models import (
    Artifact,
    DocumentVersion,
    Page,
    ProcessingRun,
    ProcessingStep,
    ProvenanceRecord,
    ReviewTask,
    SourceBlock,
    SourceEntry,
    SourceEntryBlock,
    SourceMedia,
    VocabularyEntry,
)
from app.services.book_structure import bare_headword, classify_book_text
from app.settings import get_settings
from app.storage import StorageAdapter, build_storage_adapter, read_artifact_bytes

MEDIA_NAMESPACE = "SOURCE_MEDIA"
ROLE_ENTRY = "ENTRY_ILLUSTRATION"
ROLE_NON_VOCABULARY = "NON_VOCABULARY"
ROLE_UNRESOLVED = "UNRESOLVED"
REVIEW_REASON = "SOURCE_MEDIA_ASSOCIATION_UNCERTAIN"
ASSOCIATION_METHOD = "layout-band@1.0.0"
STEP_SEQUENCE = 25
_VERIFIED = {"AUTO_VERIFIED", "HUMAN_VERIFIED"}
_OPEN = ["OPEN", "IN_PROGRESS", "ESCALATED"]
_FULL_PAGE_AREA = 0.85
_IGNORABLE = {"PAGE_NUMBER", "DECORATION", "EMPTY"}
_EPSILON = 0.002
_MIME = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png"}


@dataclass(slots=True)
class DetectedMedia:
    media_order: int
    xref: int
    bbox: dict
    payload: bytes
    mime_type: str
    extension: str
    width: int
    height: int
    extraction_method: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


@dataclass(slots=True)
class PageBlock:
    """A text block reduced to what media association needs."""

    y1: float
    y2: float
    x1: float
    x2: float
    kinds: list[str]
    starts_entry: bool
    entry_ids: list[str] = field(default_factory=list)  # ordered by entry_order


@dataclass(slots=True)
class MediaDecision:
    role: str
    source_entry_id: str | None
    confidence: float
    verification_status: str
    reason: str
    warnings: list[str] = field(default_factory=list)
    candidate_entry_ids: list[str] = field(default_factory=list)


def detect_page_media(pdf: fitz.Document, page: fitz.Page) -> list[DetectedMedia]:
    """Return every raster image placed on the page, in reading order."""
    width = float(page.rect.width) or 1.0
    height = float(page.rect.height) or 1.0
    placements = [
        info for info in page.get_image_info(xrefs=True) if int(info.get("xref") or 0) > 0
    ]
    placements.sort(key=lambda info: (round(info["bbox"][1], 2), round(info["bbox"][0], 2)))
    detected: list[DetectedMedia] = []
    for order, info in enumerate(placements, start=1):
        x0, y0, x1, y1 = info["bbox"]
        payload, extension, method, pixel_width, pixel_height = _extract_image(pdf, info["xref"])
        detected.append(
            DetectedMedia(
                media_order=order,
                xref=int(info["xref"]),
                bbox={
                    "x1": _clamp(x0 / width),
                    "y1": _clamp(y0 / height),
                    "x2": _clamp(x1 / width),
                    "y2": _clamp(y1 / height),
                    "unit": "normalized",
                },
                payload=payload,
                mime_type=_MIME[extension],
                extension="jpg" if extension == "jpeg" else extension,
                width=pixel_width,
                height=pixel_height,
                extraction_method=method,
            )
        )
    return detected


def _extract_image(pdf: fitz.Document, xref: int) -> tuple[bytes, str, str, int, int]:
    image = pdf.extract_image(xref)
    extension = str(image.get("ext", "")).lower()
    if extension in _MIME and not image.get("smask"):
        # The embedded stream itself: the exact bytes the publisher shipped.
        return (
            image["image"],
            extension,
            "pdf-embedded-stream",
            int(image["width"]),
            int(image["height"]),
        )
    # Masked or exotic encodings are decoded once and stored as lossless PNG.
    pixmap = fitz.Pixmap(pdf, xref)
    if pixmap.colorspace is not None and pixmap.colorspace.n > 3:
        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
    return pixmap.tobytes("png"), "png", "pdf-pixmap-png", pixmap.width, pixmap.height


def detect_separators(page: fitz.Page) -> list[float]:
    """Normalized y of the horizontal rules the book prints between entries."""
    width = float(page.rect.width) or 1.0
    height = float(page.rect.height) or 1.0
    rules = {
        round(((item["rect"].y0 + item["rect"].y1) / 2) / height, 4)
        for item in page.get_drawings()
        if item["rect"].width > 0.5 * width and item["rect"].height < 3
    }
    return sorted(rules)


def associate_media(
    bbox: dict,
    blocks: list[PageBlock],
    separators: list[float],
    *,
    entry_order: dict[str, int],
    previous_entry_id: str | None,
) -> MediaDecision:
    """Decide which entry a media region belongs to, or refuse to decide.

    The book places an illustration at the end of its entry, inside the band
    delimited by the horizontal rules above the headword and below the
    illustration. An association is auto-verified only when reading order and
    those rules agree; every other outcome is REVIEW_REQUIRED.
    """
    top, bottom = float(bbox["y1"]), float(bbox["y2"])
    left, right = float(bbox["x1"]), float(bbox["x2"])
    if (right - left) * (bottom - top) >= _FULL_PAGE_AREA:
        return MediaDecision(ROLE_NON_VOCABULARY, None, 1.0, "AUTO_VERIFIED", "FULL_PAGE_IMAGE")

    meaningful = [block for block in blocks if set(block.kinds) - _IGNORABLE]
    above = [block for block in meaningful if (block.y1 + block.y2) / 2 < top]
    below = [block for block in meaningful if (block.y1 + block.y2) / 2 > bottom]
    overlapping = [
        block
        for block in meaningful
        if block not in above and block not in below and block.x1 < right and block.x2 > left
    ]
    above.sort(key=lambda block: block.y2)
    below.sort(key=lambda block: block.y1)
    entry_above = [block for block in above if block.entry_ids]

    if not entry_above and any("WORD_LIST_HEADER" in block.kinds for block in above):
        # Word List title pages carry QR codes between the title and the first entry.
        return MediaDecision(
            ROLE_NON_VOCABULARY, None, 0.99, "AUTO_VERIFIED", "WORD_LIST_HEADER_RESOURCE"
        )

    warnings: list[str] = []
    if overlapping:
        warnings.append("text_overlaps_media")
    if not separators:
        warnings.append("no_separator_rules_on_page")
    if _has_side_by_side_entries(meaningful):
        # Vertical order alone cannot rank entries that sit next to each other.
        warnings.append("multi_column_layout")

    nearest_above = entry_above[-1] if entry_above else None
    nearest_below = below[0] if below else None
    owner: str | None = None
    candidates: list[str] = []

    if nearest_above is not None:
        owner = nearest_above.entry_ids[-1]
        if _rule_between(separators, nearest_above.y2, top):
            warnings.append("separator_between_entry_text_and_media")
    elif nearest_below is not None and nearest_below.entry_ids and not nearest_below.starts_entry:
        # Top of page, entry text resumes below: the entry started on an earlier page.
        owner = nearest_below.entry_ids[0]
    else:
        # Top of page with nothing of the entry on this page: it ended on the previous one.
        owner = previous_entry_id
        if _rule_between(separators, 0.0, top):
            warnings.append("separator_above_media_at_page_top")
        if owner is None:
            warnings.append("no_preceding_entry")

    if nearest_below is not None:
        if nearest_below.starts_entry:
            following = nearest_below.entry_ids[0] if nearest_below.entry_ids else None
            if following:
                candidates.append(following)
            if not _rule_between(separators, bottom, nearest_below.y1):
                warnings.append("no_separator_before_next_entry")
            if (
                owner
                and following
                and entry_order.get(following, 0) - entry_order.get(owner, 0) != 1
            ):
                warnings.append("owner_is_not_the_entry_preceding_next_headword")
        elif nearest_below.entry_ids:
            if owner != nearest_below.entry_ids[0]:
                warnings.append("media_between_different_entries")
                candidates.append(nearest_below.entry_ids[0])
            if _rule_between(separators, bottom, nearest_below.y1):
                warnings.append("separator_inside_entry")
        else:
            warnings.append("non_entry_text_below_media")

    if owner is not None:
        candidates.insert(0, owner)
    candidates = list(dict.fromkeys(candidates))
    if owner is None or warnings:
        return MediaDecision(
            ROLE_UNRESOLVED,
            None,
            0.5 if owner else 0.0,
            "REVIEW_REQUIRED",
            "LAYOUT_SIGNALS_DISAGREE" if owner else "NO_ENTRY_CONTEXT",
            warnings=warnings,
            candidate_entry_ids=candidates,
        )
    return MediaDecision(
        ROLE_ENTRY, owner, 0.98, "AUTO_VERIFIED", "ENTRY_BAND", candidate_entry_ids=candidates
    )


def _has_side_by_side_entries(blocks: list[PageBlock]) -> bool:
    entry_blocks = [block for block in blocks if block.entry_ids]
    for index, first in enumerate(entry_blocks):
        for second in entry_blocks[index + 1 :]:
            overlap = min(first.y2, second.y2) - max(first.y1, second.y1)
            shorter = min(first.y2 - first.y1, second.y2 - second.y1)
            if shorter > 0 and overlap > 0.5 * shorter and (
                first.x2 <= second.x1 or second.x2 <= first.x1
            ):
                return True
    return False


def _rule_between(separators: list[float], upper: float, lower: float) -> bool:
    return any(upper - _EPSILON <= rule <= lower + _EPSILON for rule in separators)


def extract_source_media(
    db: Session, run_id: str, *, storage: StorageAdapter | None = None
) -> dict:
    """Detect, persist and associate source media for a run. Safe to re-run.

    A re-run never duplicates media, never rewrites stored bytes, and never
    touches a row a human has already reviewed.
    """
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    version = db.get(DocumentVersion, run.document_version_id)
    if version is None:
        raise ValueError("document version not found")
    source = db.get(Artifact, version.source_artifact_id)
    if source is None:
        raise ValueError("source artifact not found")
    storage = storage or build_storage_adapter(get_settings())

    pages = (
        db.query(Page)
        .filter(Page.document_version_id == version.id)
        .order_by(Page.page_number)
        .all()
    )
    step = (
        db.query(ProcessingStep)
        .filter(
            ProcessingStep.processing_run_id == run.id,
            ProcessingStep.sequence_no == STEP_SEQUENCE,
        )
        .one_or_none()
    )
    if step is None:
        step = ProcessingStep(
            processing_run_id=run.id,
            step_type="SOURCE_MEDIA_EXTRACTION",
            sequence_no=STEP_SEQUENCE,
            processor_name="source-media-extractor",
            processor_version="1.0.0",
            configuration={"association_method": ASSOCIATION_METHOD},
            status="RUNNING",
        )
        db.add(step)
    else:
        step.status = "RUNNING"
        step.retry_count += 1
        step.error = None
    db.flush()

    layout = _RunLayout(db, run.id, pages)
    detected_count = created = reused = pages_with_media = 0
    pdf = fitz.open(source.object_key)
    try:
        if pdf.page_count != len(pages):
            raise ValueError("rendered page count does not match the source PDF")
        for page_row in pages:
            pdf_page = pdf[page_row.page_number - 1]
            detected = detect_page_media(pdf, pdf_page)
            if not detected:
                continue
            pages_with_media += 1
            detected_count += len(detected)
            separators = detect_separators(pdf_page)
            for media in detected:
                existing = (
                    db.query(SourceMedia)
                    .filter(
                        SourceMedia.processing_run_id == run.id,
                        SourceMedia.page_id == page_row.id,
                        SourceMedia.media_order == media.media_order,
                    )
                    .one_or_none()
                )
                if existing is not None:
                    if existing.sha256 != media.sha256:
                        raise ValueError(
                            f"source media changed on page {page_row.page_number}: "
                            f"{existing.sha256} != {media.sha256}"
                        )
                    reused += 1
                    continue
                artifact = _persist_media_artifact(
                    db, storage, document_sha256=version.sha256, media=media,
                    page_number=page_row.page_number,
                )
                decision = associate_media(
                    media.bbox,
                    layout.blocks(page_row.id),
                    separators,
                    entry_order=layout.entry_order,
                    previous_entry_id=layout.last_entry_before(page_row.page_number),
                )
                row = SourceMedia(
                    document_version_id=version.id,
                    processing_run_id=run.id,
                    page_id=page_row.id,
                    page_number=page_row.page_number,
                    media_order=media.media_order,
                    artifact_id=artifact.id,
                    source_entry_id=decision.source_entry_id,
                    vocabulary_entry_id=layout.vocabulary_id(decision.source_entry_id),
                    media_type="IMAGE",
                    media_role=decision.role,
                    bbox=media.bbox,
                    mime_type=media.mime_type,
                    width=media.width,
                    height=media.height,
                    sha256=media.sha256,
                    extraction_method=media.extraction_method,
                    association_method=ASSOCIATION_METHOD,
                    confidence=decision.confidence,
                    verification_status=decision.verification_status,
                    metadata_json={
                        "namespace": MEDIA_NAMESPACE,
                        "pdf_xref": media.xref,
                        "association_reason": decision.reason,
                        "warnings": decision.warnings,
                        "candidate_entry_ids": decision.candidate_entry_ids,
                        "separators_y": separators,
                    },
                )
                db.add(row)
                db.flush()
                _add_media_provenance(db, row, document_sha256=version.sha256)
                if decision.verification_status == "REVIEW_REQUIRED":
                    db.add(
                        ReviewTask(
                            processing_run_id=run.id,
                            reason_code=REVIEW_REASON,
                            status="OPEN",
                            target_entity_type="SourceMedia",
                            target_entity_id=row.id,
                            target_field_path="source_entry_id",
                            source_context={
                                "page_number": row.page_number,
                                "bbox": row.bbox,
                                "sha256": row.sha256,
                                "reason": decision.reason,
                                "warnings": decision.warnings,
                                "candidate_entry_ids": decision.candidate_entry_ids,
                            },
                            candidate_values=[],
                        )
                    )
                created += 1
    except Exception:
        db.rollback()
        raise
    finally:
        pdf.close()

    step.status = "COMPLETED"
    step.metrics = {
        "pages_scanned": len(pages),
        "pages_with_media": pages_with_media,
        "media_detected": detected_count,
        "media_created": created,
        "media_reused": reused,
    }
    db.commit()
    return {"run_id": run.id, **step.metrics}


class _RunLayout:
    """Per-run text geometry, loaded once and served page by page."""

    def __init__(self, db: Session, run_id: str, pages: list[Page]) -> None:
        self._page_numbers = {page.id: page.page_number for page in pages}
        entries = (
            db.query(SourceEntry)
            .filter(SourceEntry.processing_run_id == run_id)
            .order_by(SourceEntry.entry_order)
            .all()
        )
        self.entry_order = {entry.id: entry.entry_order for entry in entries}
        self._vocabulary = {
            item.source_entry_id: item.id
            for item in db.query(VocabularyEntry)
            .filter(VocabularyEntry.processing_run_id == run_id)
            .all()
        }
        links: dict[str, list[str]] = {}
        for link in (
            db.query(SourceEntryBlock)
            .join(SourceEntry, SourceEntry.id == SourceEntryBlock.source_entry_id)
            .filter(SourceEntry.processing_run_id == run_id)
            .all()
        ):
            links.setdefault(link.source_block_id, []).append(link.source_entry_id)
        self._blocks: dict[str, list[PageBlock]] = {}
        self._last_entry_on_page: dict[int, str] = {}
        for block in db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id).all():
            lines = [line for line in (block.raw_text or "").splitlines() if line.strip()]
            if not lines:
                continue
            bold = set((block.metadata_json or {}).get("bold_lines") or [])
            kinds = [classify_book_text(line).block_type for line in lines]
            first = " ".join(lines[0].split())
            starts_entry = kinds[0] == "ENTRY_HEAD" or (
                first in bold and bare_headword(first) is not None
            )
            entry_ids = sorted(links.get(block.id, []), key=lambda item: self.entry_order[item])
            self._blocks.setdefault(block.page_id, []).append(
                PageBlock(
                    y1=float(block.bbox["y1"]),
                    y2=float(block.bbox["y2"]),
                    x1=float(block.bbox["x1"]),
                    x2=float(block.bbox["x2"]),
                    kinds=kinds,
                    starts_entry=starts_entry and bool(entry_ids),
                    entry_ids=entry_ids,
                )
            )
            page_number = self._page_numbers.get(block.page_id)
            if entry_ids and page_number is not None:
                current = self._last_entry_on_page.get(page_number)
                if current is None or self.entry_order[entry_ids[-1]] > self.entry_order[current]:
                    self._last_entry_on_page[page_number] = entry_ids[-1]

    def blocks(self, page_id: str) -> list[PageBlock]:
        return self._blocks.get(page_id, [])

    def vocabulary_id(self, source_entry_id: str | None) -> str | None:
        return self._vocabulary.get(source_entry_id) if source_entry_id else None

    def last_entry_before(self, page_number: int) -> str | None:
        """The entry still open when the previous page ends, if that page has entries."""
        return self._last_entry_on_page.get(page_number - 1)


def _persist_media_artifact(
    db: Session,
    storage: StorageAdapter,
    *,
    document_sha256: str,
    media: DetectedMedia,
    page_number: int,
) -> Artifact:
    # Content-addressed: identical bytes always land on the identical key.
    key = (
        f"source-media/{document_sha256}/p{page_number:04d}-"
        f"{media.media_order:02d}-{media.sha256}.{media.extension}"
    )
    existing = db.query(Artifact).filter(Artifact.object_key == key).one_or_none()
    if existing is not None:
        if existing.sha256 != media.sha256:
            raise ValueError(f"immutable artifact collision at {key}")
        if not storage.exists(key):
            storage.put_bytes(key, media.payload)
        return existing
    stored = storage.put_bytes(key, media.payload)
    artifact = Artifact(
        artifact_type=MEDIA_NAMESPACE,
        storage_provider=stored["provider"],
        bucket=stored["bucket"],
        object_key=stored["object_key"],
        mime_type=media.mime_type,
        byte_size=stored["byte_size"],
        sha256=stored["sha256"],
        metadata_json={"immutable": True, "namespace": MEDIA_NAMESPACE},
    )
    db.add(artifact)
    db.flush()
    return artifact


def _add_media_provenance(db: Session, media: SourceMedia, *, document_sha256: str) -> None:
    db.add(
        ProvenanceRecord(
            processing_run_id=media.processing_run_id,
            target_entity_type="SourceMedia",
            target_entity_id=media.id,
            target_field_path="artifact",
            provenance_type="SOURCE_DIRECT",
            source_entry_id=media.source_entry_id,
            page_id=media.page_id,
            source_text=media.sha256,
            metadata_json={
                "method": f"{media.extraction_method}@1.0.0",
                "namespace": MEDIA_NAMESPACE,
                "document_sha256": document_sha256,
                "page_number": media.page_number,
                "bbox": media.bbox,
                "pdf_xref": (media.metadata_json or {}).get("pdf_xref"),
            },
        )
    )
    if media.source_entry_id:
        db.add(
            ProvenanceRecord(
                processing_run_id=media.processing_run_id,
                target_entity_type="SourceMedia",
                target_entity_id=media.id,
                target_field_path="source_entry_id",
                provenance_type="SOURCE_LAYOUT",
                source_entry_id=media.source_entry_id,
                page_id=media.page_id,
                source_text=media.source_entry_id,
                metadata_json={"method": ASSOCIATION_METHOD, "confidence": media.confidence},
            )
        )


def resolve_source_media_review(
    db: Session, task: ReviewTask, *, resolution: dict, reviewer_id: str, audit: dict
) -> dict:
    """Apply a human decision to one media association."""
    media = db.get(SourceMedia, task.target_entity_id)
    if media is None:
        raise ValueError("review target not found")
    decision = audit["decision"]
    classification = str(resolution.get("classification") or "").upper()
    if decision == "REJECT":
        task.status = "ESCALATED"
        db.commit()
        return _review_result(task, media, decision)

    if classification == "NOT_VOCABULARY_MEDIA":
        media.media_role = ROLE_NON_VOCABULARY
        media.source_entry_id = None
        media.vocabulary_entry_id = None
    else:
        entry_id = resolution.get("source_entry_id") or (
            (task.source_context.get("candidate_entry_ids") or [None])[0]
        )
        entry = db.get(SourceEntry, entry_id) if entry_id else None
        if entry is None or entry.processing_run_id != media.processing_run_id:
            raise ValueError("accepted media requires a source_entry_id from the same run")
        vocabulary = (
            db.query(VocabularyEntry)
            .filter(VocabularyEntry.source_entry_id == entry.id)
            .one_or_none()
        )
        media.media_role = ROLE_ENTRY
        media.source_entry_id = entry.id
        media.vocabulary_entry_id = vocabulary.id if vocabulary else None
    media.verification_status = "HUMAN_VERIFIED"
    media.confidence = 1.0
    media.association_method = "human-review"
    media.metadata_json = {**(media.metadata_json or {}), "human_media_review": audit}
    db.add(
        ProvenanceRecord(
            processing_run_id=task.processing_run_id,
            target_entity_type="SourceMedia",
            target_entity_id=media.id,
            target_field_path="source_entry_id",
            provenance_type="HUMAN_REVIEW",
            source_entry_id=media.source_entry_id,
            page_id=media.page_id,
            source_text=media.source_entry_id or classification,
            metadata_json={"review_task_id": task.id, "reviewer_id": reviewer_id.strip()},
        )
    )
    task.status = "RESOLVED"
    db.commit()
    return _review_result(task, media, decision)


def _review_result(task: ReviewTask, media: SourceMedia, decision: str) -> dict:
    return {
        "run_id": task.processing_run_id,
        "task_id": task.id,
        "status": task.status,
        "source_media_id": media.id,
        "media_role": media.media_role,
        "source_entry_id": media.source_entry_id,
        "verification_status": media.verification_status,
        "decision": decision,
    }


def source_media_metrics(
    db: Session, run_id: str, *, storage: StorageAdapter | None = None, verify_bytes: bool = True
) -> dict:
    """Integrity accounting for the Source Media Fidelity Gate."""
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    rows = db.query(SourceMedia).filter(SourceMedia.processing_run_id == run_id).all()
    step = (
        db.query(ProcessingStep)
        .filter(
            ProcessingStep.processing_run_id == run_id,
            ProcessingStep.sequence_no == STEP_SEQUENCE,
        )
        .one_or_none()
    )
    step_metrics = (step.metrics or {}) if step is not None else {}
    page_count = db.query(Page).filter(Page.document_version_id == run.document_version_id).count()
    provenance = {
        (item.target_entity_id, item.target_field_path)
        for item in db.query(ProvenanceRecord)
        .filter(
            ProvenanceRecord.processing_run_id == run_id,
            ProvenanceRecord.target_entity_type == "SourceMedia",
        )
        .all()
    }
    entry_ids = {
        item.id
        for item in db.query(SourceEntry.id).filter(SourceEntry.processing_run_id == run_id).all()
    }
    settings = get_settings()
    missing_artifact = missing_sha = broken_artifact = broken_provenance = 0
    for row in rows:
        artifact = db.get(Artifact, row.artifact_id)
        if artifact is None:
            missing_artifact += 1
            continue
        if not row.sha256 or not artifact.sha256:
            missing_sha += 1
        elif artifact.sha256 != row.sha256:
            broken_artifact += 1
        elif verify_bytes:
            try:
                payload = (
                    storage.read_bytes(artifact.object_key)
                    if storage is not None
                    else read_artifact_bytes(
                        storage_provider=artifact.storage_provider,
                        object_key=artifact.object_key,
                        settings=settings,
                    )
                )
            except (BotoCoreError, ClientError, OSError, ValueError):
                missing_artifact += 1
            else:
                if hashlib.sha256(payload).hexdigest() != row.sha256:
                    broken_artifact += 1
        if (row.id, "artifact") not in provenance or (
            row.source_entry_id
            and (
                (row.id, "source_entry_id") not in provenance
                or row.source_entry_id not in entry_ids
            )
        ):
            broken_provenance += 1

    entry_bound = [row for row in rows if row.media_role == ROLE_ENTRY]
    unresolved = sum(
        row.verification_status not in _VERIFIED or row.media_role == ROLE_UNRESOLVED
        for row in rows
    )
    return {
        "total_pages": page_count,
        "pages_scanned": int(step_metrics.get("pages_scanned", 0)),
        "pages_with_media": len({row.page_id for row in rows}),
        "media_detected": int(step_metrics.get("media_detected", 0)),
        "media_extracted": len(rows) - missing_artifact,
        "media_persisted": len(rows),
        "associated_with_source_entry": sum(bool(row.source_entry_id) for row in entry_bound),
        "associated_with_vocabulary_entry": sum(
            bool(row.vocabulary_entry_id) for row in entry_bound
        ),
        "excluded_non_vocabulary": sum(row.media_role == ROLE_NON_VOCABULARY for row in rows),
        "auto_verified": sum(row.verification_status == "AUTO_VERIFIED" for row in rows),
        "human_verified": sum(row.verification_status == "HUMAN_VERIFIED" for row in rows),
        "unbound_media": sum(
            row.media_role == ROLE_ENTRY and not row.source_entry_id for row in rows
        ),
        "unresolved_media": unresolved,
        "missing_media": max(int(step_metrics.get("media_detected", 0)) - len(rows), 0),
        "missing_artifact": missing_artifact,
        "missing_sha256": missing_sha,
        "broken_artifact": broken_artifact,
        "broken_provenance": broken_provenance,
        "open_media_reviews": db.query(ReviewTask)
        .filter(
            ReviewTask.processing_run_id == run_id,
            ReviewTask.target_entity_type == "SourceMedia",
            ReviewTask.status.in_(_OPEN),
        )
        .count(),
    }


def serialize_source_media(db: Session, media: SourceMedia) -> dict:
    """The public, binary-free description of one source media item."""
    artifact = db.get(Artifact, media.artifact_id)
    return {
        "media_id": media.id,
        "namespace": MEDIA_NAMESPACE,
        "media_type": media.media_type,
        "media_role": media.media_role,
        "page": media.page_number,
        "bbox": media.bbox,
        "width": media.width,
        "height": media.height,
        "sha256": media.sha256,
        "artifact": {
            "artifact_id": media.artifact_id,
            "object_key": artifact.object_key if artifact else None,
            "mime_type": media.mime_type,
            "byte_size": artifact.byte_size if artifact else None,
        },
        "verification_status": media.verification_status,
        "provenance": {
            "source_entry_id": media.source_entry_id,
            "extraction_method": media.extraction_method,
            "association_method": media.association_method,
            "confidence": media.confidence,
        },
    }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
