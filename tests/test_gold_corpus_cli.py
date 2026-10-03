import json

from app.gold_corpus_cli import main


def test_reports_real_not_ready_state_when_annotations_are_absent(tmp_path, capsys):
    output = tmp_path / "readiness.json"

    assert main(["--annotations", str(tmp_path / "missing"), "--output", str(output)]) == 0

    result = json.loads(output.read_text())
    assert result["status"] == "NOT_READY"
    assert result["human_verified_count"] == 0
    assert result["publish_allowed"] is False
    assert "NOT_READY" in capsys.readouterr().out


def test_require_ready_fails_closed_when_annotations_are_absent(tmp_path):
    assert main(["--annotations", str(tmp_path / "missing"), "--require-ready"]) == 1
