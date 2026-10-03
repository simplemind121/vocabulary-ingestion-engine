"""Source Media Gold: a media-only overlay on the 30-page Gold Sample.

The textual Gold annotations stay byte-for-byte untouched. Each Gold page gets
one overlay recording which source media the page really contains and which
entry each item belongs to. Only an explicit human decision can mark an
overlay HUMAN_VERIFIED; a page without media is verified as media_count = 0.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# This module is imported by release gates that run without the application
# dependencies installed, so it must stay standard-library only at import time.
ROLE_ENTRY = "ENTRY_ILLUSTRATION"
ROLE_NON_VOCABULARY = "NON_VOCABULARY"
MEDIA_ANNOTATION_SCHEMA_VERSION = "1.0"
DECISIONS = {"APPROVE", "CORRECT_ASSOCIATION", "NOT_VOCABULARY_MEDIA"}
REQUIRED_MEDIA_CHECKS = {
    "compared_with_original_page",
    "no_source_media_missing",
    "every_association_checked",
}
_COMPARED_FIELDS = ("media_order", "sha256", "media_role", "lemma")


def build_media_prediction_from_run(
    db: Any, run_id: str, *, page_number: int, sample_id: str, document_sha256: str
) -> dict[str, Any]:
    """What the machine detected on one page, keyed by lemma rather than run ids."""
    from app.models import Page, ProcessingRun, SourceMedia, VocabularyEntry

    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    page = (
        db.query(Page)
        .filter(
            Page.document_version_id == run.document_version_id,
            Page.page_number == page_number,
        )
        .one_or_none()
    )
    if page is None:
        raise ValueError(f"run has no page {page_number}")
    media = []
    for row in (
        db.query(SourceMedia)
        .filter(SourceMedia.processing_run_id == run_id, SourceMedia.page_id == page.id)
        .order_by(SourceMedia.media_order)
        .all()
    ):
        vocabulary = (
            db.get(VocabularyEntry, row.vocabulary_entry_id) if row.vocabulary_entry_id else None
        )
        metadata = row.metadata_json or {}
        media.append(
            {
                "media_order": row.media_order,
                "sha256": row.sha256,
                "bbox": row.bbox,
                "width": row.width,
                "height": row.height,
                "mime_type": row.mime_type,
                "media_role": row.media_role,
                "lemma": vocabulary.lemma if vocabulary else None,
                "machine": {
                    "verification_status": row.verification_status,
                    "confidence": row.confidence,
                    "reason": metadata.get("association_reason"),
                    "warnings": metadata.get("warnings") or [],
                    "source_media_id": row.id,
                },
            }
        )
    return {
        "sample_id": sample_id,
        "document_sha256": document_sha256,
        "page_number": page_number,
        "processing_run_id": run_id,
        "media": media,
    }


def build_media_draft(text_annotation: dict[str, Any], prediction: dict[str, Any]) -> dict:
    """A DRAFT overlay from a machine prediction. Never verified by construction."""
    return {
        "media_annotation_schema_version": MEDIA_ANNOTATION_SCHEMA_VERSION,
        "sample_id": text_annotation["sample_id"],
        "document_sha256": text_annotation["document_sha256"],
        "page_number": text_annotation["page_number"],
        "page_image_sha256": text_annotation["page_image_sha256"],
        "review_status": "DRAFT",
        "reviewer_id": None,
        "reviewed_at": None,
        "media_count": len(prediction["media"]),
        "media": [
            {
                **{key: item[key] for key in _COMPARED_FIELDS},
                "bbox": item["bbox"],
                "width": item["width"],
                "height": item["height"],
                "mime_type": item["mime_type"],
                "human_decision": None,
            }
            for item in prediction["media"]
        ],
        "missing_media_reported": False,
        "review_notes": ["MACHINE_DRAFT_ONLY: every item must be checked against the page."],
    }


def validate_media_annotation(annotation: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if annotation.get("media_annotation_schema_version") != MEDIA_ANNOTATION_SCHEMA_VERSION:
        errors.append("media_annotation_schema_version_must_be_1.0")
    for name in ("document_sha256", "page_image_sha256"):
        if not _is_sha256(annotation.get(name)):
            errors.append(f"{name}_invalid")
    media = annotation.get("media")
    if not isinstance(media, list):
        errors.append("media_must_be_array")
        media = []
    if annotation.get("media_count") != len(media):
        errors.append("media_count_mismatch")
    if [item.get("media_order") for item in media] != list(range(1, len(media) + 1)):
        errors.append("media_order_must_be_contiguous")
    verified = annotation.get("review_status") == "HUMAN_VERIFIED"
    for item in media:
        label = f"media_{item.get('media_order')}"
        if not _is_sha256(item.get("sha256")):
            errors.append(f"{label}:sha256_invalid")
        role = item.get("media_role")
        if role == ROLE_ENTRY and not _nonempty(item.get("lemma")):
            errors.append(f"{label}:entry_media_requires_lemma")
        if role == ROLE_NON_VOCABULARY and item.get("lemma") is not None:
            errors.append(f"{label}:non_vocabulary_media_must_not_have_lemma")
        if verified:
            if role not in {ROLE_ENTRY, ROLE_NON_VOCABULARY}:
                errors.append(f"{label}:unresolved_media_cannot_be_verified")
            if item.get("human_decision") not in DECISIONS:
                errors.append(f"{label}:human_decision_required")
    if verified:
        if not _nonempty(annotation.get("reviewer_id")):
            errors.append("reviewer_id_required_for_human_verified")
        if annotation.get("missing_media_reported"):
            errors.append("missing_media_blocks_verification")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}


def evaluate_media_readiness(
    text_annotations: list[dict[str, Any]], media_annotations: list[dict[str, Any]]
) -> dict[str, Any]:
    """30/30 Gold pages must carry a human-verified media overlay."""
    errors: list[str] = []
    by_sample = {item.get("sample_id"): item for item in media_annotations}
    if len(media_annotations) != len(by_sample):
        errors.append("duplicate_media_annotation")
    verified = 0
    for text in text_annotations:
        sample_id = text.get("sample_id")
        overlay = by_sample.get(sample_id)
        if overlay is None:
            errors.append(f"{sample_id}:media_annotation_missing")
            continue
        for name in ("document_sha256", "page_number", "page_image_sha256"):
            if overlay.get(name) != text.get(name):
                errors.append(f"{sample_id}:{name}_differs_from_text_gold")
        result = validate_media_annotation(overlay)
        errors.extend(f"{sample_id}:{error}" for error in result["errors"])
        if overlay.get("review_status") == "HUMAN_VERIFIED" and result["status"] == "PASS":
            verified += 1
    extra = sorted(set(by_sample) - {item.get("sample_id") for item in text_annotations})
    errors.extend(f"{sample_id}:not_a_gold_page" for sample_id in extra)
    if verified != len(text_annotations) or len(text_annotations) != 30:
        errors.append(f"media_human_verified_count_must_equal_30:{verified}")
    media = [item for overlay in media_annotations for item in overlay.get("media") or []]
    return {
        "status": "READY_TO_FREEZE" if not errors else "NOT_READY",
        "gold_pages_checked": verified,
        "pages_with_media": sum(bool(item.get("media")) for item in media_annotations),
        "pages_verified_without_media": sum(
            item.get("review_status") == "HUMAN_VERIFIED" and not item.get("media")
            for item in media_annotations
        ),
        "expected_source_media": len(media),
        "entry_illustrations": sum(item.get("media_role") == ROLE_ENTRY for item in media),
        "non_vocabulary_media": sum(
            item.get("media_role") == ROLE_NON_VOCABULARY for item in media
        ),
        "errors": errors,
    }


def evaluate_media_regression(
    text_annotations: list[dict[str, Any]],
    media_annotations: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    """The Source Media Fidelity Gate over the Gold Sample."""
    readiness = evaluate_media_readiness(text_annotations, media_annotations)
    predicted = {item.get("sample_id"): item for item in predictions}
    expected = detected = extracted = verified = correct = 0
    unbound = unresolved = missing_sha = 0
    failed: list[dict[str, Any]] = []
    for overlay in sorted(media_annotations, key=lambda item: item.get("page_number", 0)):
        sample_id = overlay.get("sample_id")
        truth = overlay.get("media") or []
        machine = (predicted.get(sample_id) or {}).get("media")
        expected += len(truth)
        if overlay.get("review_status") == "HUMAN_VERIFIED":
            verified += len(truth)
        if machine is None:
            failed.append({"sample_id": sample_id, "reason": "prediction_missing"})
            continue
        detected += len(machine)
        extracted += sum(_is_sha256(item.get("sha256")) for item in machine)
        missing_sha += sum(not _is_sha256(item.get("sha256")) for item in machine)
        unresolved += sum(
            item.get("media_role") not in {ROLE_ENTRY, ROLE_NON_VOCABULARY} for item in machine
        )
        unbound += sum(
            item.get("media_role") == ROLE_ENTRY and not item.get("lemma") for item in machine
        )
        truth_by_hash = {item["sha256"]: item for item in truth}
        correct += sum(
            item.get("sha256") in truth_by_hash
            and _comparable(item) == _comparable(truth_by_hash[item["sha256"]])
            for item in machine
        )
        if [_comparable(item) for item in machine] != [_comparable(item) for item in truth]:
            failed.append({"sample_id": sample_id, "reason": "media_mismatch"})
    blocking = []
    if readiness["status"] != "READY_TO_FREEZE":
        blocking.append("media_gold_not_human_verified")
    if failed:
        blocking.append("media_regression_mismatch")
    for name, value in (
        ("unbound_media", unbound),
        ("unresolved_media", unresolved),
        ("missing_sha256", missing_sha),
    ):
        if value:
            blocking.append(name)
    return {
        "gate": "GOLD_SOURCE_MEDIA_FIDELITY",
        "ruleset_version": "1.0.0",
        "status": "PASS" if not blocking else "FAIL",
        "blocking_failures": blocking,
        "metrics": {
            "gold_pages_checked": readiness["gold_pages_checked"],
            "gold_pages_total": len(text_annotations),
            "pages_with_media": readiness["pages_with_media"],
            "pages_verified_without_media": readiness["pages_verified_without_media"],
            "expected_source_media": expected,
            "detected_source_media": detected,
            "extracted_source_media": extracted,
            "verified_source_media": verified,
            "correct_entry_association": correct,
            "unbound": unbound,
            "unresolved": unresolved,
            "missing_sha256": missing_sha,
        },
        "failed_samples": failed,
        "readiness_errors": readiness["errors"],
    }


def media_ground_truth_sha256(annotation: dict[str, Any]) -> str:
    payload = json.dumps(annotation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def load_json_directory(path: str | Path) -> list[dict[str, Any]]:
    root = Path(path)
    if not root.is_dir():
        return []
    return [json.loads(item.read_text(encoding="utf-8")) for item in sorted(root.glob("*.json"))]


class GoldMediaReviewSession:
    """Local, human-only sign-off for the media overlay of each Gold page."""

    def __init__(self, packet_dir: str | Path, annotations_dir: str | Path) -> None:
        self.packet_dir = Path(packet_dir).resolve()
        self.annotations_dir = Path(annotations_dir).resolve()
        packet = json.loads((self.packet_dir / "packet.json").read_text(encoding="utf-8"))
        self.items = {int(item["page_number"]): item for item in packet["items"]}
        if not self.items:
            raise ValueError("media review packet has no pages")
        self.annotations_dir.mkdir(parents=True, exist_ok=True)

    def list_pages(self) -> dict[str, Any]:
        pages = []
        for page_number in sorted(self.items):
            overlay = self._load(page_number)
            pages.append(
                {
                    "page_number": page_number,
                    "sample_id": overlay["sample_id"],
                    "review_status": overlay["review_status"],
                    "media_count": overlay["media_count"],
                    "missing_media_reported": overlay["missing_media_reported"],
                }
            )
        return {
            "pages": pages,
            "human_verified_count": sum(p["review_status"] == "HUMAN_VERIFIED" for p in pages),
            "media_total": sum(p["media_count"] for p in pages),
        }

    def get_page(self, page_number: int) -> dict[str, Any]:
        item = self._item(page_number)
        overlay = self._load(page_number)
        machine = {entry["media_order"]: entry for entry in item.get("media") or []}
        return {
            **overlay,
            "image_url": f"/api/media/pages/{page_number}/image",
            "page_lemmas": item.get("page_lemmas") or [],
            "media": [
                {
                    **entry,
                    "content_url": (
                        f"/api/media/pages/{page_number}/items/{entry['media_order']}/content"
                    ),
                    "machine": machine.get(entry["media_order"], {}).get("machine"),
                }
                for entry in overlay["media"]
            ],
        }

    def image_path(self, page_number: int) -> Path:
        return self._safe(self._item(page_number)["page_image"])

    def media_path(self, page_number: int, media_order: int) -> Path:
        for entry in self._item(page_number).get("media") or []:
            if entry["media_order"] == media_order:
                return self._safe(entry["file"])
        raise ValueError("media item is not in the review packet")

    def verify_page(
        self,
        page_number: int,
        *,
        reviewer_id: str,
        checks: list[str],
        decisions: list[dict[str, Any]],
        notes: str | None,
    ) -> dict[str, Any]:
        reviewer = (reviewer_id or "").strip()
        if not reviewer:
            raise ValueError("reviewer_id is required")
        if set(checks) != REQUIRED_MEDIA_CHECKS:
            missing = sorted(REQUIRED_MEDIA_CHECKS - set(checks))
            raise ValueError("all media verification checks are required: " + ",".join(missing))
        overlay = self._load(page_number)
        if overlay["review_status"] == "HUMAN_VERIFIED":
            raise ValueError("page media is already HUMAN_VERIFIED")
        by_order = {int(item.get("media_order", -1)): item for item in decisions}
        if sorted(by_order) != [item["media_order"] for item in overlay["media"]]:
            raise ValueError("a decision is required for every detected media item")
        for item in overlay["media"]:
            decision = by_order[item["media_order"]]
            choice = str(decision.get("decision") or "").upper()
            if choice not in DECISIONS:
                raise ValueError("decision must be APPROVE, CORRECT_ASSOCIATION or NOT_VOCABULARY_MEDIA")
            if choice == "APPROVE" and item["media_role"] not in {ROLE_ENTRY, ROLE_NON_VOCABULARY}:
                raise ValueError("an unresolved machine association cannot be approved as is")
            if choice == "CORRECT_ASSOCIATION":
                lemma = str(decision.get("lemma") or "").strip()
                if not lemma:
                    raise ValueError("a corrected association requires the entry lemma")
                item["media_role"], item["lemma"] = ROLE_ENTRY, lemma
            elif choice == "NOT_VOCABULARY_MEDIA":
                item["media_role"], item["lemma"] = ROLE_NON_VOCABULARY, None
            item["human_decision"] = choice
        overlay.update(
            {
                "review_status": "HUMAN_VERIFIED",
                "reviewer_id": reviewer,
                "reviewed_at": datetime.now(UTC).isoformat(),
                "missing_media_reported": False,
                "review_notes": [note for note in [(notes or "").strip()] if note],
            }
        )
        result = validate_media_annotation(overlay)
        if result["status"] != "PASS":
            raise ValueError("cannot verify media overlay: " + ",".join(result["errors"]))
        self._write(overlay)
        return {"page_number": page_number, "review_status": "HUMAN_VERIFIED"}

    def report_missing_media(self, page_number: int, *, reviewer_id: str, notes: str) -> dict:
        if not (reviewer_id or "").strip() or not (notes or "").strip():
            raise ValueError("reviewer_id and a description of the missing media are required")
        overlay = self._load(page_number)
        if overlay["review_status"] == "HUMAN_VERIFIED":
            raise ValueError("page media is already HUMAN_VERIFIED")
        overlay["missing_media_reported"] = True
        overlay["review_notes"] = [
            *overlay.get("review_notes", []),
            f"MISSING_MEDIA reported by {reviewer_id.strip()}: {notes.strip()}",
        ]
        self._write(overlay)
        return {"page_number": page_number, "review_status": "DRAFT", "missing_media_reported": True}

    def _item(self, page_number: int) -> dict[str, Any]:
        if page_number not in self.items:
            raise ValueError("page is not in the media review packet")
        return self.items[page_number]

    def _load(self, page_number: int) -> dict[str, Any]:
        item = self._item(page_number)
        target = self.annotations_dir / f"{item['sample_id']}.json"
        source = target if target.exists() else self._safe(item["draft"])
        overlay = json.loads(source.read_text(encoding="utf-8"))
        draft = json.loads(self._safe(item["draft"]).read_text(encoding="utf-8"))
        for name in ("sample_id", "document_sha256", "page_number", "page_image_sha256"):
            if overlay.get(name) != draft.get(name):
                raise ValueError(f"media annotation identity mismatch on page {page_number}")
        if [m["sha256"] for m in overlay["media"]] != [m["sha256"] for m in draft["media"]]:
            raise ValueError(f"media annotation is stale for the packet on page {page_number}")
        return overlay

    def _safe(self, relative: str) -> Path:
        path = (self.packet_dir / relative).resolve()
        if self.packet_dir not in path.parents:
            raise ValueError("packet path escapes the packet directory")
        return path

    def _write(self, overlay: dict[str, Any]) -> None:
        write_json_atomic(self.annotations_dir / f"{overlay['sample_id']}.json", overlay)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def _comparable(item: dict[str, Any]) -> tuple:
    return tuple(item.get(name) for name in _COMPARED_FIELDS)


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
