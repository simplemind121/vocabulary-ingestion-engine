"""Run-bound Source Media commands: pass, release evidence, Gold review packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from app.db import SessionLocal
from app.models import Artifact, DocumentVersion, ProcessingRun, SourceMedia, VocabularyEntry
from app.services.full_book_evidence import source_media_pipeline_sha256
from app.services.gates import evaluate_source_media_gate
from app.services.gold import publish_gold_release
from app.services.gold_media import (
    build_media_draft,
    build_media_prediction_from_run,
    load_json_directory,
    write_json_atomic,
)
from app.services.source_media import extract_source_media, source_media_metrics
from app.settings import get_settings
from app.storage import read_artifact_bytes

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run_pass = commands.add_parser("pass", help="extract and associate source media for a run")
    run_pass.add_argument("run_id")
    run_pass.add_argument("--publish", action="store_true")

    evidence = commands.add_parser("evidence", help="write redacted full-book media evidence")
    evidence.add_argument("run_id")
    evidence.add_argument("--output", type=Path, required=True)

    packet = commands.add_parser("packet", help="build the Gold media review packet")
    packet.add_argument("run_id")
    packet.add_argument("--annotations", type=Path, required=True)
    packet.add_argument("--page-images", type=Path, required=True)
    packet.add_argument("--output", type=Path, required=True)
    packet.add_argument("--predictions-out", type=Path, required=True)
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        if args.command == "pass":
            result = extract_source_media(db, args.run_id)
            gate = evaluate_source_media_gate(db, args.run_id)
            result = {"extraction": result, "gate": gate}
            if args.publish:
                release = publish_gold_release(db, args.run_id)
                result["gold_release"] = {
                    "id": release.id,
                    "version": release.version,
                    "sha256": release.sha256,
                    "record_count": release.record_count,
                }
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if gate["status"] != "FAIL" else 1
        if args.command == "evidence":
            payload = build_source_media_evidence(db, args.run_id)
            write_json_atomic(args.output, payload)
            print(json.dumps(payload["metrics"], sort_keys=True))
            return 0
        summary = build_gold_media_packet(
            db,
            args.run_id,
            annotations=load_json_directory(args.annotations),
            page_images=args.page_images,
            output=args.output,
            predictions_out=args.predictions_out,
        )
        print(json.dumps(summary, sort_keys=True))
        return 0


def build_source_media_evidence(db, run_id: str) -> dict:
    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise ValueError("processing run not found")
    version = db.get(DocumentVersion, run.document_version_id)
    lemmas = {
        item.id: item.lemma
        for item in db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id)
    }
    rows = (
        db.query(SourceMedia)
        .filter(SourceMedia.processing_run_id == run_id)
        .order_by(SourceMedia.page_number, SourceMedia.media_order)
        .all()
    )
    hashes = hashlib.sha256("\n".join(row.sha256 for row in rows).encode()).hexdigest()
    return {
        "evidence_schema_version": "1.0",
        "source_document_sha256": version.sha256,
        "processing_run_id": run_id,
        "source_media_pipeline_sha256": source_media_pipeline_sha256(ROOT),
        "vocabulary_entry_count": len(lemmas),
        "metrics": source_media_metrics(db, run_id),
        "media_sha256_set_sha256": hashes,
        "media": [
            {
                "page": row.page_number,
                "media_order": row.media_order,
                "sha256": row.sha256,
                "media_role": row.media_role,
                "verification_status": row.verification_status,
                "association_method": row.association_method,
                "association_reason": (row.metadata_json or {}).get("association_reason"),
                "lemma": lemmas.get(row.vocabulary_entry_id),
            }
            for row in rows
        ],
        "copyrighted_media_included": False,
    }


def build_gold_media_packet(
    db,
    run_id: str,
    *,
    annotations: list[dict],
    page_images: Path,
    output: Path,
    predictions_out: Path,
) -> dict:
    if len(annotations) != 30:
        raise ValueError("Gold Sample v1 requires exactly 30 text annotations")
    settings = get_settings()
    items = []
    media_total = 0
    for annotation in sorted(annotations, key=lambda item: item["page_number"]):
        sample_id = annotation["sample_id"]
        page_number = annotation["page_number"]
        image = page_images / f"{sample_id}.png"
        if hashlib.sha256(image.read_bytes()).hexdigest() != annotation["page_image_sha256"]:
            raise ValueError(f"page image hash mismatch for {sample_id}")
        (output / "page-images").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image, output / "page-images" / image.name)
        prediction = build_media_prediction_from_run(
            db,
            run_id,
            page_number=page_number,
            sample_id=sample_id,
            document_sha256=annotation["document_sha256"],
        )
        write_json_atomic(predictions_out / f"{sample_id}.json", prediction)
        write_json_atomic(
            output / "drafts" / f"{sample_id}.json", build_media_draft(annotation, prediction)
        )
        media = []
        for item in prediction["media"]:
            row = db.get(SourceMedia, item["machine"]["source_media_id"])
            artifact = db.get(Artifact, row.artifact_id)
            payload = read_artifact_bytes(
                storage_provider=artifact.storage_provider,
                object_key=artifact.object_key,
                settings=settings,
            )
            if hashlib.sha256(payload).hexdigest() != item["sha256"]:
                raise ValueError(f"stored media hash mismatch on page {page_number}")
            name = f"media/{sample_id}-{item['media_order']:02d}{Path(artifact.object_key).suffix}"
            (output / "media").mkdir(parents=True, exist_ok=True)
            (output / name).write_bytes(payload)
            media.append({"media_order": item["media_order"], "file": name, "machine": item["machine"]})
        media_total += len(media)
        items.append(
            {
                "sample_id": sample_id,
                "page_number": page_number,
                "page_image": f"page-images/{image.name}",
                "draft": f"drafts/{sample_id}.json",
                "page_lemmas": [entry["lemma"] for entry in annotation.get("entries") or []],
                "media": media,
            }
        )
    write_json_atomic(
        output / "packet.json",
        {"packet_version": "1.0", "processing_run_id": run_id, "items": items},
    )
    return {
        "pages": len(items),
        "pages_with_media": sum(bool(item["media"]) for item in items),
        "media": media_total,
    }


if __name__ == "__main__":
    sys.exit(main())
