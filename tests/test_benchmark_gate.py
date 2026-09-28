import pytest

from app.services.benchmark import run_gold_benchmark
from app.services.benchmark_gate import assert_benchmark_gate, evaluate_benchmark_gate


def _truth():
    return {
        "blocks": [{"text": "sample [ˈsɑːmpl]"}],
        "entries": [{"lemma": "sample", "raw_text": "sample [ˈsɑːmpl] n. 样品"}],
        "vocabulary": [
            {
                "lemma": "sample",
                "display_form": "sample",
                "ipa": "ˈsɑːmpl",
                "part_of_speech": "n.",
                "definition": "样品",
            }
        ],
    }


def test_exact_gold_benchmark_passes_regression_gate():
    truth = _truth()
    report = run_gold_benchmark(truth, truth)

    result = assert_benchmark_gate(report)

    assert result["status"] == "PASS"
    assert result["publish_allowed"] is True
    assert result["blocking_failures"] == []


def test_any_gold_regression_is_blocking_by_default():
    truth = _truth()
    prediction = _truth()
    prediction["vocabulary"][0]["definition"] = "样本"
    report = run_gold_benchmark(prediction, truth)

    result = evaluate_benchmark_gate(report)

    assert result["status"] == "FAIL"
    assert result["publish_allowed"] is False
    assert "canonical_field_accuracy" in result["blocking_failures"]
    assert "exact_match" in result["blocking_failures"]
    with pytest.raises(RuntimeError, match="Gold benchmark regression gate failed"):
        assert_benchmark_gate(report)


def test_missing_layers_fail_closed():
    result = evaluate_benchmark_gate({"exact_match": True, "layers": {}})

    assert result["status"] == "FAIL"
    assert set(result["blocking_failures"]) == {
        "canonical_field_accuracy",
        "ocr_f1",
        "segmentation_f1",
    }
