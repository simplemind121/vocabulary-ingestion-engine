import json

from app.gold_regression_cli import main
from app.services.benchmark import run_gold_benchmark


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


def test_cli_returns_zero_for_exact_gold_report(tmp_path, capsys):
    truth = _truth()
    report_path = tmp_path / "benchmark-report.json"
    report_path.write_text(
        json.dumps(run_gold_benchmark(truth, truth), ensure_ascii=False),
        encoding="utf-8",
    )

    assert main([str(report_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "PASS"
    assert output["publish_allowed"] is True


def test_cli_returns_one_for_regression(tmp_path, capsys):
    truth = _truth()
    prediction = _truth()
    prediction["vocabulary"][0]["definition"] = "样本"
    report_path = tmp_path / "benchmark-report.json"
    report_path.write_text(
        json.dumps(run_gold_benchmark(prediction, truth), ensure_ascii=False),
        encoding="utf-8",
    )

    assert main([str(report_path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "FAIL"
    assert output["publish_allowed"] is False


def test_cli_returns_two_for_malformed_report(tmp_path, capsys):
    report_path = tmp_path / "benchmark-report.json"
    report_path.write_text("{not-json", encoding="utf-8")

    assert main([str(report_path)]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ERROR"
    assert output["publish_allowed"] is False
