from app.services.benchmark import run_gold_benchmark


def _truth():
    return {
        "blocks": [{"text": "medication* [ˌmedɪˈkeɪʃn]"}, {"text": "n. 药；药物"}],
        "entries": [{"lemma": "medication", "raw_text": "medication* [ˌmedɪˈkeɪʃn]\nn. 药；药物"}],
        "vocabulary": [
            {
                "lemma": "medication",
                "display_form": "medication",
                "ipa": "ˌmedɪˈkeɪʃn",
                "part_of_speech": "n.",
                "definition": "药；药物",
            }
        ],
    }


def test_gold_benchmark_passes_only_on_exact_layered_match():
    truth = _truth()
    result = run_gold_benchmark(truth, truth)
    assert result["status"] == "PASS"
    assert result["exact_match"] is True
    assert result["layers"]["ocr"]["f1"] == 1.0
    assert result["layers"]["segmentation"]["f1"] == 1.0
    assert result["layers"]["canonical"]["field_accuracy"] == 1.0


def test_gold_benchmark_reports_layer_that_drifted():
    truth = _truth()
    prediction = _truth()
    prediction["vocabulary"][0]["definition"] = "药物治疗"
    result = run_gold_benchmark(prediction, truth)
    assert result["status"] == "FAIL"
    assert result["layers"]["ocr"]["exact_match"] is True
    assert result["layers"]["segmentation"]["exact_match"] is True
    assert result["layers"]["canonical"]["exact_match"] is False
    assert result["layers"]["canonical"]["fields"]["definition"]["accuracy"] == 0.0


def test_gold_benchmark_detects_missing_entry_even_if_ocr_matches():
    truth = _truth()
    prediction = _truth()
    prediction["entries"] = []
    result = run_gold_benchmark(prediction, truth)
    assert result["status"] == "FAIL"
    assert result["layers"]["ocr"]["exact_match"] is True
    assert result["layers"]["segmentation"]["recall"] == 0.0
