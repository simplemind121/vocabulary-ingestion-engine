import json
import random

from app.evaluation.gold import DEV, TEST, page_text, split_of
from app.evaluation.metrics import cer, levenshtein, ned, wer, word_scores
from app.evaluation.readers import evaluate, gold_order, reader_lines
from app.evaluation_cli import main as cli


def _naive(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        previous, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (x != y))
    return row[-1]


def test_edit_distance_matches_the_textbook_definition():
    rng = random.Random(7)
    for _ in range(500):
        a = "".join(rng.choice("ab c") for _ in range(rng.randint(0, 40)))
        b = "".join(rng.choice("abd ") for _ in range(rng.randint(0, 70)))
        assert levenshtein(a, b) == _naive(a, b)
    assert levenshtein(["I", "was", "walking"], ["I", "walking"]) == 1


def test_rates_and_word_scores():
    assert cer("I was walkng", "I was walking") == 1 / 13
    assert ned("abc", "abd") == 1 / 3
    assert wer("I was walking home", "I was walking") == 1 / 3
    # Curly quotes and spacing do not count as errors.
    assert cer("I’m  here", "I'm here") == 0
    scores = word_scores("home I was walking walking", "I was walking home")
    assert scores["recall"] == 1 and scores["precision"] == 0.8


GOLD = {
    5: {"page": 5, "kind": "unit-explanation", "unit": 3, "title": "Present **simple**", "blocks": [
        {"type": "section", "letter": "A", "blocks": [{"type": "examples", "items": ["I *work* in a bank.", "She {{works}} there."]}]}]},
    6: {"page": 6, "kind": "unit-exercises", "unit": 5, "title": None, "blocks": [
        {"type": "exercise", "id": "5.1", "instruction": "Complete.", "blocks": [{"type": "items", "items": [{"n": "1", "md": "He {{}} late."}]}]}]},
}


def test_gold_text_and_the_fixed_split():
    assert page_text(GOLD[5]) == "Present simple A I work in a bank. She works there."
    assert page_text(GOLD[6]) == "5.1 Complete. 1 He late."
    assert split_of(GOLD[5]) == DEV and split_of(GOLD[6]) == TEST
    assert split_of({"page": 310, "unit": None}) == TEST


def test_lines_are_put_in_gold_order():
    reference = "first line here then the second line and the third one"
    assert gold_order(["the third one", "first line here", "then the second line"], reference) == [
        "first line here", "then the second line", "the third one"]


LINES = {
    5: [
        {"text": "Present simple", "readings": {"other": "Present simp1e"}},
        {"text": "A I work in a bank.", "readings": {"other": "A I work in a bank."}},
        {"text": "She works there.", "readings": {"other": "A I work in a bank."}},
    ],
    6: [{"text": "5.1 Complete.", "readings": {}}, {"text": "1 He late.", "readings": {}}],
}


def test_a_band_repeated_for_the_next_line_counts_once():
    assert reader_lines(LINES[5])["other"] == ["Present simp1e", "A I work in a bank."]


def test_readers_are_scored_per_split(tmp_path, capsys):
    report = evaluate(LINES, GOLD)
    voted = report["readers"]["voted"]
    assert voted[DEV]["word_f1"] == 1 and voted[DEV]["cer"] == 0 and voted[TEST]["cer"] == 0
    assert report["readers"]["other"][DEV]["word_recall"] < 1
    gold = tmp_path / "gold"
    gold.mkdir()
    for number, tree in GOLD.items():
        (gold / f"p{number:03d}.json").write_text(json.dumps(tree))
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps({str(k): v for k, v in LINES.items()}))
    assert cli(["readers", "--lines", str(lines), "--gold", str(gold), "--out", str(tmp_path / "r.json")]) == 0
    assert "voted" in capsys.readouterr().out
    assert json.loads((tmp_path / "r.json").read_text())["pages"]["voted"][0]["page"] == 5
