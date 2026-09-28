from app.services.gold_sample import REQUIRED_LAYOUT_TAGS, validate_gold_sample_manifest


def _manifest():
    tags = sorted(REQUIRED_LAYOUT_TAGS)
    pages = []
    for index in range(30):
        pages.append(
            {
                "sample_id": f"sample-{index + 1:02d}",
                "document_sha256": "a" * 64,
                "page_number": index + 1,
                "page_image_sha256": "b" * 64,
                "layout_tags": [tags[index]] if index < len(tags) else ["NORMAL"],
                "ground_truth_path": f"annotations/sample-{index + 1:02d}.json",
                "review_status": "HUMAN_VERIFIED",
                "reviewer_id": "reviewer-1",
                "annotation_schema_version": "1.0",
            }
        )
    return {"dataset_version": "1.0", "pages": pages}


def test_gold_sample_manifest_passes_only_with_30_verified_pages_and_full_coverage():
    result = validate_gold_sample_manifest(_manifest())
    assert result["status"] == "PASS"
    assert result["page_count"] == 30
    assert result["human_verified_pages"] == 30
    assert result["missing_layout_tags"] == []


def test_gold_sample_manifest_fails_when_required_layout_class_is_missing():
    manifest = _manifest()
    for page in manifest["pages"]:
        page["layout_tags"] = ["NORMAL"]
    result = validate_gold_sample_manifest(manifest)
    assert result["status"] == "FAIL"
    assert "OCR_HARD" in result["missing_layout_tags"]


def test_gold_sample_manifest_fails_if_any_page_is_not_human_verified():
    manifest = _manifest()
    manifest["pages"][0]["review_status"] = "AUTO_VERIFIED"
    result = validate_gold_sample_manifest(manifest)
    assert result["status"] == "FAIL"
    assert "page[1]:review_status_not_human_verified" in result["errors"]
