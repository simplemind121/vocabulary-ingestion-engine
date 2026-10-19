import json

import fitz

from app.structure.grammar_export import build_book
from app.structure_cli import main as cli

PROFILE = {
    "id": "book",
    "name": "语法",
    "nameEn": "Grammar",
    "groups": [["Tenses", "时态", 1, 1]],
    "parts": [["key", "Key", "答案", 3, 3]],
    "keys": {"key": {"pages": [3, 3], "heading": r"\*\*(\d+\.\d+)\*\*"}},
}


def _trees() -> dict:
    explain = {"page": 1, "kind": "unit-explanation", "unit": 1, "title": "Present continuous", "blocks": [
        {"type": "section", "letter": "A", "blocks": [
            {"type": "text", "md": "I am **doing**."},
            {"type": "figure", "box": [0.2, 0.3, 0.6, 0.6], "about": "a picture", "exact": True},
        ]},
    ], "checked": {"invented": [], "dropped_lines": [], "by": "t"}}
    exercises = {"page": 2, "kind": "unit-exercises", "unit": 1, "title": None, "blocks": [
        {"type": "exercise", "id": "1.1", "instruction": "Complete.", "blocks": [{"type": "items", "items": [{"n": "1", "md": "I {{}} working."}]}]},
    ]}
    key = {"page": 3, "kind": "other", "unit": None, "title": "Key", "blocks": [
        {"type": "columns", "columns": [[{"type": "text", "md": "**UNIT 1**"}, {"type": "text", "md": "**1.1**"}], [{"type": "items", "items": [{"n": "1", "md": "am"}]}]]},
    ]}
    return {1: explain, 2: exercises, 3: key}


def test_the_book_has_units_parts_keys_and_pictures():
    book = build_book(_trees(), PROFILE, {1: [{"src": "p001-1.jpg", "width": 48}]})
    assert book["units"] == [{"unit": 1, "title": "Present continuous", "explain": [1], "exercises": [2]}]
    assert book["groups"] == [{"en": "Tenses", "zh": "时态", "first": 1, "last": 1}]
    assert book["parts"] == [{"id": "key", "en": "Key", "zh": "答案", "first": 3, "last": 3}]
    assert book["key"] == {"1.1": [{"type": "items", "items": [{"n": "1", "md": "am"}]}]}
    figure = book["pages"]["1"]["blocks"][0]["blocks"][1]
    assert figure["src"] == "p001-1.jpg" and figure["width"] == 48
    assert "checked" not in book["pages"]["1"]


def test_the_command_line_writes_the_book_and_cuts_the_pictures(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    for number, tree in _trees().items():
        (pages / f"p{number:03d}.json").write_text(json.dumps(tree))
    pdf = tmp_path / "book.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    doc.save(pdf)
    doc.close()
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(PROFILE))
    out = tmp_path / "site"
    assert cli(["export-grammar", "--pages", str(pages), "--pdf", str(pdf), "--profile", str(profile), str(out)]) == 0
    book = json.loads((out / "grammar.json").read_text())
    assert sorted(book["pages"]) == ["1", "2", "3"]
    assert (out / "fig" / "p001-1.jpg").stat().st_size > 0
    # An exact figure keeps its box: 40% of the page is 48% of the text width.
    assert book["pages"]["1"]["blocks"][0]["blocks"][1]["width"] == 48
