import json

import fitz
import pytest

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.db import SessionLocal
from app.idr import BoundingBox, TextBlock
from app.services.pipeline import run_pipeline
from app.structure.evidence import run_lines
from app.structure.plan import compile_plan
from app.structure.store import (
    ACCEPTED,
    REVIEW_REQUIRED,
    as_tree,
    compile_and_save,
    current_pages,
    save_page,
)
from app.structure_cli import main as cli

LINES = [
    {"text": "Unit 6", "box": [0.9, 0.0, 1.0, 0.05], "readings": {}},
    {"text": "Past continuous (I was doing)", "box": [0.1, 0.05, 0.6, 0.1], "readings": {}},
    {"text": "We use the past continuous for an action in progress.", "box": [0.1, 0.2, 0.9, 0.25], "readings": {}},
    {"text": "1 I was walking home when it started to rain.", "box": [0.1, 0.3, 0.9, 0.35], "readings": {"other": "I was walklng home"}},
    {"text": "2 What were you doing at 10 o'clock?", "box": [0.1, 0.4, 0.9, 0.45], "readings": {}},
]

PLAN = """K explain 6 | Past continuous (**I was doing**)
- 1
S A
P L3 b=past continuous
C
X L4 | L5
|C
F 0.6 0.3 0.9 0.5 a man walking in the rain
/C
"""


def test_a_plan_compiles_to_a_page_tree_with_clean_checks():
    tree = compile_plan(12, PLAN, LINES, by="tester")
    assert tree["kind"] == "unit-explanation" and tree["unit"] == 6
    assert tree["title"] == "Past continuous (**I was doing**)"
    section = tree["blocks"][0]
    assert section["type"] == "section" and section["letter"] == "A"
    assert section["blocks"][0] == {"type": "text", "md": "We use the **past continuous** for an action in progress."}
    columns = section["blocks"][1]["columns"]
    assert columns[0][0]["items"][0].startswith("1 I was walking")
    assert columns[1][0]["type"] == "figure" and columns[1][0]["box"] == [0.6, 0.3, 0.9, 0.5]
    assert tree["checked"] == {"invented": [], "dropped_lines": [], "by": "tester"}


def test_invented_words_and_dropped_lines_are_reported():
    plan = "K exercises 6\n- 1,2\nP We use the past simple.\nI 1 I was walking home when it started to rain.\n"
    checked = compile_plan(13, plan, LINES, by="tester")["checked"]
    assert checked["invented"] == ["simple"]
    assert checked["dropped_lines"] == [
        "3:We use the past continuous for an action in progre",
        "5:2 What were you doing at 10 o'clock?",
    ]
    # A word only the scan's hidden text layer read is not invented.
    assert compile_plan(13, plan, LINES, ["simple"], by="tester")["checked"]["invented"] == []


def test_items_gaps_and_unknown_directives():
    tree = compile_plan(14, "E 6.1 What were you doing?\nI 1 What {{were you doing}} at 10 o'clock?\nI 2 L5\n- 1-4", LINES, by="t")
    exercise = tree["blocks"][0]
    assert exercise["id"] == "6.1"
    items = exercise["blocks"][0]["items"]
    assert items == [{"n": "1", "md": "What {{were you doing}} at 10 o'clock?"}, {"n": "2", "md": "What were you doing at 10 o'clock?"}]
    assert tree["checked"]["invented"] == []
    with pytest.raises(ValueError):
        compile_plan(14, "Q nonsense", LINES, by="t")


class PageOcr:
    name = "page-ocr"
    version = "1"

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        return OcrPageResult(
            page_number=page.page_number,
            blocks=[
                TextBlock(text=line["text"], bbox=BoundingBox(*line["box"]), reading_order=i, confidence=0.99)
                for i, line in enumerate(LINES)
            ],
            engine_name=self.name,
            engine_version=self.version,
        )


@pytest.fixture
def run_id(client):
    doc = fitz.open()
    doc.new_page()
    payload = doc.tobytes()
    doc.close()
    run = client.post("/api/v1/documents", files={"file": ("unit6.pdf", payload, "application/pdf")}).json()["run_id"]
    db = SessionLocal()
    try:
        run_pipeline(db, run, publish=False, ocr_adapter=PageOcr())
    finally:
        db.close()
    return run


def test_plans_are_compiled_against_the_runs_own_lines_and_versioned(run_id, tmp_path):
    db = SessionLocal()
    try:
        assert [line["text"] for line in run_lines(db, run_id)[1]] == [line["text"] for line in LINES]
        first = compile_and_save(db, run_id, 1, "K other\nP We use the past simple.", author="tester")
        assert first.version == 1 and first.status == REVIEW_REQUIRED
        second = compile_and_save(db, run_id, 1, PLAN, author="tester")
        assert second.version == 2 and second.status == ACCEPTED and second.source_plan == PLAN
        assert current_pages(db, run_id)[1].id == second.id
        assert as_tree(second)["blocks"][0]["letter"] == "A"
        with pytest.raises(ValueError):
            save_page(db, run_id, {"page": 7, "blocks": []}, producer="import")
    finally:
        db.close()

    # The command line exports the current pages and imports them again as a new version.
    pages = tmp_path / "pages"
    assert cli(["export", "--run", run_id, str(pages)]) == 0
    exported = json.loads((pages / "p001.json").read_text())
    assert exported["checked"]["invented"] == [] and exported["title"] == "Past continuous (**I was doing**)"
    assert cli(["import", "--run", run_id, str(pages)]) == 0
    db = SessionLocal()
    try:
        assert current_pages(db, run_id)[1].version == 3
        assert current_pages(db, run_id)[1].producer == "import"
    finally:
        db.close()


def test_the_command_line_compiles_outside_the_database(tmp_path, capsys):
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps({"12": LINES}))
    pdf = tmp_path / "book.pdf"
    doc = fitz.open()
    for _ in range(12):
        doc.new_page()
    doc.save(pdf)
    doc.close()
    plan = tmp_path / "p012.plan"
    plan.write_text(PLAN)
    assert cli(["compile", "--lines", str(lines), "--pdf", str(pdf), "--page", "12", str(plan), "--out", str(tmp_path / "pages")]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"invented": [], "dropped_lines": [], "by": "claude"}
    assert json.loads((tmp_path / "pages" / "p012.json").read_text()) == compile_plan(12, PLAN, LINES, by="claude")


WORD_LINES = [
    {"text": "include > vt.包含，包括", "box": [0.1, 0.2, 0.9, 0.22], "readings": {}},
    {"text": "/In'klu:d/ 记词根记忆：in（进入）+clude（关）→关进里面一包含，包括", "box": [0.1, 0.22, 0.9, 0.24], "readings": {}},
    {"text": "圆Tour includes bike.此次旅行提供自行车。", "box": [0.1, 0.24, 0.9, 0.26], "readings": {}},
    {"text": "关注微信公众号获取更多资料", "box": [0.1, 0.95, 0.9, 0.97], "readings": {}},
]


def test_word_entries_compile_with_their_fields_and_chinese_is_checked():
    plan = (
        "K words 01\n- 4\n"
        "V include | ɪnˈkluːd | vt. 包含，包括\n"
        "M 记 词根记忆：in（进入）+clude（关）→关进里面→包含，包括\n"
        "M 例 Tour **includes** bike. 此次旅行提供自行车。\n"
    )
    tree = compile_plan(12, plan, WORD_LINES, by="t")
    assert tree["kind"] == "word-list" and tree["unit"] == 1
    word = tree["blocks"][0]
    assert word == {"type": "word", "w": "include", "ipa": "ɪnˈkluːd", "senses": "vt. 包含，包括", "fields": [
        ["记", "词根记忆：in（进入）+clude（关）→关进里面→包含，包括"], ["例", "Tour **includes** bike. 此次旅行提供自行车。"]]}
    assert tree["checked"]["invented"] == [] and tree["checked"]["dropped_lines"] == []
    # A Chinese character no reader read is invented; a Chinese line left out is dropped.
    wrong = compile_plan(12, "K words 01\n- 4\nV include | | vt. 包含，囊括\nM 记 词根记忆：in（进入）+clude（关）→关进里面→包含，包括", WORD_LINES, by="t")
    assert wrong["checked"]["invented"] == ["囊"]
    assert wrong["checked"]["dropped_lines"] == ["3:圆Tour includes bike.此次旅行提供自行车。"]
    with pytest.raises(ValueError):
        compile_plan(12, "M 记 a field before any word", WORD_LINES, by="t")
