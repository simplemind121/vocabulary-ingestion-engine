import json

from app.gold_dataset_benchmark_cli import main
from app.services.gold_sample import REQUIRED_LAYOUT_TAGS


def _write_corpus(directory, *, drift=False):
    directory.mkdir()
    tags = sorted(REQUIRED_LAYOUT_TAGS)
    for index in range(30):
        page = index + 1
        sample_id = f"gold-v1-p{page:04d}"
        annotation = {
            "annotation_schema_version": "1.0",
            "sample_id": sample_id,
            "document_sha256": "a" * 64,
            "page_number": page,
            "page_image_sha256": f"{page:064x}",
            "layout_tags": [tags[index]] if index < len(tags) else ["NORMAL"],
            "review_status": "HUMAN_VERIFIED",
            "reviewer_id": "human-reviewer",
            "blocks": [{"text": f"word-{page}"}],
            "entries": [{"lemma": f"word-{page}", "raw_text": f"word-{page}"}],
            "vocabulary": [{"lemma": f"word-{page}", "display_form": f"word-{page}"}],
            "review_notes": [],
        }
        if drift and page == 8:
            annotation["blocks"][0]["text"] = "human correction"
        (directory / f"{sample_id}.json").write_text(json.dumps(annotation))


def _copy_as_predictions(annotations, predictions):
    predictions.mkdir()
    for source in annotations.glob("*.json"):
        payload = json.loads(source.read_text())
        payload["review_status"] = "DRAFT"
        payload["reviewer_id"] = None
        (predictions / source.name).write_text(json.dumps(payload))


def test_real_dataset_benchmark_requires_verified_annotations_and_exact_predictions(
    tmp_path, capsys
):
    annotations = tmp_path / "annotations"
    predictions = tmp_path / "predictions"
    _write_corpus(annotations)
    _copy_as_predictions(annotations, predictions)
    output = tmp_path / "report.json"

    assert main(
        [
            "--annotations",
            str(annotations),
            "--predictions",
            str(predictions),
            "--output",
            str(output),
        ]
    ) == 0

    report = json.loads(output.read_text())
    assert report["status"] == "PASS"
    assert report["page_count"] == 30
    assert report["failed_samples"] == []
    assert "PASS" in capsys.readouterr().out


def test_real_dataset_benchmark_reports_page_level_regression(tmp_path):
    annotations = tmp_path / "annotations"
    predictions = tmp_path / "predictions"
    _write_corpus(annotations, drift=True)
    _copy_as_predictions(annotations, predictions)
    prediction = predictions / "gold-v1-p0008.json"
    payload = json.loads(prediction.read_text())
    payload["blocks"][0]["text"] = "machine output"
    prediction.write_text(json.dumps(payload))

    output = tmp_path / "report.json"
    assert main(
        [
            "--annotations",
            str(annotations),
            "--predictions",
            str(predictions),
            "--output",
            str(output),
        ]
    ) == 1
    report = json.loads(output.read_text())
    assert report["failed_samples"] == ["gold-v1-p0008"]
