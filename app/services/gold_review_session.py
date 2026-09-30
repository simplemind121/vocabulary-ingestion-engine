from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.gold_annotation import promote_annotation_to_human_verified
from app.services.gold_corpus import evaluate_corpus_readiness

REQUIRED_HUMAN_CHECKS = {
    "source_blocks_match",
    "entry_boundaries_match",
    "canonical_fields_match",
    "page_boundaries_match",
}
NON_TEXT_CLASSIFICATIONS = {"IMAGE_ONLY", "NON_TEXT_PAGE", "FRONT_MATTER"}


class GoldReviewSession:
    def __init__(self, packet_dir: str | Path, annotations_dir: str | Path) -> None:
        self.packet_dir = Path(packet_dir).resolve()
        self.annotations_dir = Path(annotations_dir).resolve()
        manifest = json.loads((self.packet_dir / "packet.json").read_text(encoding="utf-8"))
        self.items = {int(item["page_number"]): item for item in manifest["items"]}
        if not self.items:
            raise ValueError("review packet has no pages")
        self.annotations_dir.mkdir(parents=True, exist_ok=True)

    def list_pages(self) -> dict[str, Any]:
        pages = []
        annotations = []
        for page_number in sorted(self.items):
            annotation = self._load_effective_annotation(page_number)
            annotations.append(annotation)
            pages.append(
                {
                    "page_number": page_number,
                    "sample_id": annotation["sample_id"],
                    "review_status": annotation.get("review_status", "DRAFT"),
                    "reviewer_id": annotation.get("reviewer_id"),
                    "layout_tags": annotation.get("layout_tags", []),
                    "entry_count": len(annotation.get("entries") or []),
                    "review_flags": self.items[page_number].get("review_flags", []),
                }
            )
        readiness = evaluate_corpus_readiness(annotations)
        return {"pages": pages, "readiness": readiness}

    def get_page(self, page_number: int) -> dict[str, Any]:
        item = self._item(page_number)
        annotation = self._load_effective_annotation(page_number)
        records = []
        entries = annotation.get("entries") or []
        vocabulary = annotation.get("vocabulary") or []
        if len(entries) != len(vocabulary):
            raise ValueError(f"entry/vocabulary count mismatch on page {page_number}")
        for index, (entry, vocab) in enumerate(zip(entries, vocabulary, strict=True)):
            records.append(
                {
                    "index": index,
                    "lemma": entry.get("lemma") or vocab.get("lemma") or "",
                    "raw_text": entry.get("raw_text") or "",
                    "continuation_type": entry.get("continuation_type"),
                    "source_pages": entry.get("source_pages") or [page_number],
                    "display_form": vocab.get("display_form"),
                    "ipa": vocab.get("ipa"),
                    "part_of_speech": vocab.get("part_of_speech"),
                    "definition": vocab.get("definition"),
                }
            )
        return {
            "page_number": page_number,
            "sample_id": annotation["sample_id"],
            "review_status": annotation.get("review_status", "DRAFT"),
            "reviewer_id": annotation.get("reviewer_id"),
            "layout_tags": annotation.get("layout_tags", []),
            "review_flags": item.get("review_flags", []),
            "block_count": len(annotation.get("blocks") or []),
            "records": records,
            "review_notes": annotation.get("review_notes") or [],
            "image_url": f"/api/pages/{page_number}/image",
        }

    def image_path(self, page_number: int) -> Path:
        item = self._item(page_number)
        return self._safe_packet_path(item["page_image"])

    def verify_page(
        self,
        page_number: int,
        *,
        reviewer_id: str,
        checks: list[str],
        records: list[dict[str, Any]],
        page_classification: str | None,
        notes: str | None,
    ) -> dict[str, Any]:
        reviewer = reviewer_id.strip()
        if not reviewer:
            raise ValueError("reviewer_id is required")
        if set(checks) != REQUIRED_HUMAN_CHECKS:
            missing = sorted(REQUIRED_HUMAN_CHECKS - set(checks))
            raise ValueError("all human verification checks are required: " + ",".join(missing))

        annotation = self._load_effective_annotation(page_number)
        if annotation.get("review_status") == "HUMAN_VERIFIED":
            raise ValueError("page is already HUMAN_VERIFIED")
        entries = annotation.get("entries") or []
        vocabulary = annotation.get("vocabulary") or []
        if len(entries) != len(vocabulary) or len(records) != len(entries):
            raise ValueError("reviewed record count must match the machine draft")

        reviewed_entries = []
        reviewed_vocabulary = []
        for index, (entry, vocab, record) in enumerate(
            zip(entries, vocabulary, records, strict=True)
        ):
            if int(record.get("index", -1)) != index:
                raise ValueError("reviewed records must preserve source order")
            lemma = str(record.get("lemma", "")).strip()
            if not lemma:
                raise ValueError(f"lemma is required for record {index + 1}")
            source_pages = record.get("source_pages")
            if (
                not isinstance(source_pages, list)
                or not source_pages
                or not all(isinstance(page, int) and page > 0 for page in source_pages)
                or page_number not in source_pages
            ):
                raise ValueError(f"source_pages are invalid for record {index + 1}")
            continuation = record.get("continuation_type") or None
            if continuation not in {None, "CROSS_PAGE"}:
                raise ValueError(f"continuation_type is invalid for record {index + 1}")

            reviewed_entry = dict(entry)
            reviewed_entry.update(
                {
                    "lemma": lemma,
                    "continuation_type": continuation,
                    "source_pages": source_pages,
                }
            )
            reviewed_vocab = dict(vocab)
            reviewed_vocab.update(
                {
                    "lemma": lemma,
                    "display_form": _optional_text(record.get("display_form")),
                    "ipa": _optional_text(record.get("ipa")),
                    "part_of_speech": _optional_text(record.get("part_of_speech")),
                    "definition": _optional_text(record.get("definition")),
                }
            )
            reviewed_entries.append(reviewed_entry)
            reviewed_vocabulary.append(reviewed_vocab)

        blocks = annotation.get("blocks") or []
        classification = (page_classification or "").strip().upper()
        if not blocks:
            if classification not in NON_TEXT_CLASSIFICATIONS:
                raise ValueError("a page without machine blocks requires an explicit classification")
            blocks = [
                {
                    "source_block_id": f"human-p{page_number:04d}-classification",
                    "text": classification,
                    "raw_text": "",
                    "block_type": "IMAGE" if classification == "IMAGE_ONLY" else "NON_TEXT",
                    "reading_order": 0,
                    "bbox": {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0, "unit": "normalized"},
                    "confidence": 1.0,
                    "source_engine": "human-review",
                }
            ]

        annotation["blocks"] = blocks
        annotation["entries"] = reviewed_entries
        annotation["vocabulary"] = reviewed_vocabulary
        review_notes = list(annotation.get("review_notes") or [])
        if notes and notes.strip():
            review_notes.append(f"HUMAN_REVIEW_NOTE:{notes.strip()}")
        review_notes.append(
            "HUMAN_SIGN_OFF:"
            + json.dumps(
                {
                    "reviewer_id": reviewer,
                    "verified_at": datetime.now(UTC).isoformat(),
                    "checks": sorted(REQUIRED_HUMAN_CHECKS),
                    "page_classification": classification or None,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        annotation["review_notes"] = review_notes
        promoted = promote_annotation_to_human_verified(
            annotation,
            reviewer_id=reviewer,
            page_image_sha256=annotation["page_image_sha256"],
        )
        self._write_annotation(promoted)
        return self.get_page(page_number)

    def flag_page(self, page_number: int, *, reviewer_id: str, notes: str) -> dict[str, Any]:
        reviewer = reviewer_id.strip()
        issue = notes.strip()
        if not reviewer or not issue:
            raise ValueError("reviewer_id and issue notes are required")
        annotation = self._load_effective_annotation(page_number)
        if annotation.get("review_status") == "HUMAN_VERIFIED":
            raise ValueError("verified annotations must be reopened before flagging")
        review_notes = list(annotation.get("review_notes") or [])
        review_notes.append(
            f"HUMAN_REVIEW_FLAG:{reviewer}:{datetime.now(UTC).isoformat()}:{issue}"
        )
        annotation["review_notes"] = review_notes
        annotation["review_status"] = "DRAFT"
        annotation["reviewer_id"] = None
        self._write_annotation(annotation)
        return self.get_page(page_number)

    def _item(self, page_number: int) -> dict[str, Any]:
        try:
            return self.items[page_number]
        except KeyError as exc:
            raise ValueError("page is not in the Gold review packet") from exc

    def _load_packet_annotation(self, page_number: int) -> dict[str, Any]:
        item = self._item(page_number)
        return json.loads(self._safe_packet_path(item["annotation"]).read_text(encoding="utf-8"))

    def _load_effective_annotation(self, page_number: int) -> dict[str, Any]:
        packet = self._load_packet_annotation(page_number)
        self._assert_identity(packet, packet, page_number)
        target = self._annotation_target(packet["sample_id"])
        if target.is_file():
            effective = json.loads(target.read_text(encoding="utf-8"))
            self._assert_identity(packet, effective, page_number)
            return effective
        return packet

    @staticmethod
    def _assert_identity(
        packet: dict[str, Any], effective: dict[str, Any], page_number: int
    ) -> None:
        immutable_fields = (
            "annotation_schema_version",
            "sample_id",
            "document_sha256",
            "page_number",
            "page_image_sha256",
            "layout_tags",
        )
        mismatches = [
            field for field in immutable_fields if effective.get(field) != packet.get(field)
        ]
        if packet.get("page_number") != page_number:
            mismatches.append("packet.page_number")
        if mismatches:
            raise ValueError(
                "Gold annotation identity does not match the frozen review packet: "
                + ",".join(sorted(set(mismatches)))
            )

    def _safe_packet_path(self, relative: str) -> Path:
        path = (self.packet_dir / relative).resolve()
        if self.packet_dir not in path.parents:
            raise ValueError("review packet path escapes packet directory")
        if not path.is_file():
            raise ValueError(f"review packet file is missing: {relative}")
        return path

    def _write_annotation(self, annotation: dict[str, Any]) -> None:
        target = self._annotation_target(annotation["sample_id"])
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(annotation, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)

    def _annotation_target(self, sample_id: str) -> Path:
        target = (self.annotations_dir / f"{sample_id}.json").resolve()
        if target.parent != self.annotations_dir:
            raise ValueError("Gold annotation path escapes annotations directory")
        return target


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
