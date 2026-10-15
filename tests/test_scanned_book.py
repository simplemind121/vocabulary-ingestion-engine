"""A scanned Chinese-English vocabulary book with per-page headword checklists."""

import fitz

from app.adapters.ocr_base import OcrPageInput, OcrPageResult
from app.db import SessionLocal
from app.idr import BoundingBox, TextBlock
from app.models import (
    Pronunciation,
    ReviewTask,
    SourceBlock,
    VocabularyEntry,
    VocabularyField,
)
from app.services.field_parser import parse_source_entry
from app.services.page_checklist import apply_headword_checklists, compare_page
from app.services.pipeline import run_pipeline
from app.services.review import resolve_review_task
from app.services.segmentation import _segment_blocks

PAGE_ROWS = {
    1: [  # preface: a layout sample, no checklist
        "本书结构",
        "sample[sampl]n.样例",
    ],
    2: ["WordList1", "x[y]n.占位", "x"],
    3: ["WordList1", "a[b]n.占位", "a"],
    4: ["WordList1", "c[d]n.占位", "c"],
    5: ["WordList1", "e[f]n.占位", "e"],
    6: [
        "WordList2",
        "compose[kampauz]vt.组成，构成；使",
        "平静，使镇静",
        "【记】词根记忆：com（共同）+pos（放）+e→组成",
        "【例】The boy wondered how it was composed.这个小男孩想知道。",
        "fraud[fro：d]n.欺诈；骗子",
        "【题】Harold was a(n) ____.(2003.9)",
        "A)alien B)client",
        "【解】选D。alien：外侨",
        "【考】presume on（不正当地）利用",
        "21 compose fraud",
    ],
    7: [
        "WordList2",
        "【例】It is a fraud continued from the previous page.",
        "GUE[ink：]vt.招致，遭受",
        "impart[impa：t］vt.告知",
        "incur impart 22",
    ],
}


class ScannedBookOcr:
    name = "paddleocr"
    version = "test"

    def extract_page(self, page: OcrPageInput) -> OcrPageResult:
        rows = PAGE_ROWS[page.page_number]
        blocks = []
        for order, text in enumerate(rows):
            last = order == len(rows) - 1 and page.page_number > 1
            top = 0.95 if last else 0.05 + order * 0.07
            blocks.append(
                TextBlock(
                    text=text,
                    bbox=BoundingBox(0.1, top, 0.9, top + 0.03),
                    reading_order=order,
                    confidence=0.97,
                )
            )
        return OcrPageResult(
            page_number=page.page_number,
            blocks=blocks,
            engine_name=self.name,
            engine_version=self.version,
            metadata={},
        )


def _upload(client):
    doc = fitz.open()
    for _ in PAGE_ROWS:
        doc.new_page()
    payload = doc.tobytes()
    doc.close()
    return client.post(
        "/api/v1/documents", files={"file": ("scanned-book.pdf", payload, "application/pdf")}
    ).json()["run_id"]


def test_compare_page_confirms_or_explains_every_headword():
    assert compare_page(["compose", "fraud"], ["21 compose fraud"])["agrees"] is True
    assert compare_page(["press", "impress"], ["impresspress"])["agrees"] is True
    result = compare_page(["GUE", "impart"], ["incur impart 22"])
    assert result["agrees"] is False
    assert result["headwords_not_in_checklist"] == ["gue"]
    assert result["unmatched_checklist_text"] == "incur"
    missing = compare_page(["impart"], ["incur impart"])
    assert missing["headwords_not_in_checklist"] == []
    assert missing["unmatched_checklist_text"] == "incur"


def test_bracketed_markers_exam_fields_and_glued_headwords_parse():
    parsed = parse_source_entry(PAGE_ROWS[6][1:10])
    assert parsed.lemma == "compose"
    assert parsed.ipa == "kampauz"
    assert parsed.senses == [{"pos": "vt.", "definition": "组成，构成；使平静，使镇静"}]
    assert parsed.memory_notes == ["词根记忆：com（共同）+pos（放）+e→组成"]
    fraud = parse_source_entry(PAGE_ROWS[6][5:10])
    assert fraud.exam_questions == ["Harold was a(n) ____.(2003.9) A)alien B)client"]
    assert fraud.exam_explanations == ["选D。alien：外侨"]
    assert fraud.exam_notes == ["presume on（不正当地）利用"]
    assert parse_source_entry(["impart[impa：t］vt.告知"]).ipa == "impa：t"


def test_running_word_list_header_does_not_cut_a_cross_page_entry():
    class Block:
        def __init__(self, block_id, text):
            self.id, self.page_id, self.raw_text, self.metadata_json = block_id, block_id, text, {}

    blocks = [
        Block("p1", "WordList2\nfraud[fro：d]n.欺诈"),
        Block("p2", "WordList2\n【例】It continues on the next page.\nincur[ink：]vt.招致"),
        Block("p3", "WordList3\nrefuge[refju：d3]n.庇护所"),
    ]
    entries = _segment_blocks(blocks, {"p1": 1, "p2": 2, "p3": 3})
    assert [(entry.lemma, entry.word_list) for entry in entries] == [
        ("fraud", 2),
        ("incur", 2),
        ("refuge", 3),
    ]
    assert "continues on the next page" in entries[0].raw_text
    assert entries[0].page_numbers == [1, 2]


def test_a_checklist_finding_the_text_no_longer_shows_is_closed_and_can_return(client):
    run_id = _upload(client)
    db = SessionLocal()
    try:
        run_pipeline(db, run_id, ocr_adapter=ScannedBookOcr())

        def findings():
            return {
                task.status: task
                for task in db.query(ReviewTask).filter(
                    ReviewTask.processing_run_id == run_id,
                    ReviewTask.reason_code == "HEADWORD_NOT_IN_CHECKLIST",
                )
            }

        block = db.get(SourceBlock, findings()["OPEN"].target_entity_id)
        original = dict(block.metadata_json or {})
        block.metadata_json = {
            **original,
            "machine_arbitration": {"status": "ACCEPTED", "text": "incur [x] vt.招致，遭受"},
        }
        db.commit()
        assert apply_headword_checklists(db, run_id)["review_tasks_withdrawn"] == 1
        assert set(findings()) == {"NOT_APPLICABLE"}

        block.metadata_json = original
        db.commit()
        assert apply_headword_checklists(db, run_id)["review_tasks_created"] == 1
        assert set(findings()) == {"NOT_APPLICABLE", "OPEN"}
    finally:
        db.close()


def test_scanned_book_stops_for_checklist_disagreements_then_completes(client):
    run_id = _upload(client)
    db = SessionLocal()
    try:
        first = run_pipeline(db, run_id, ocr_adapter=ScannedBookOcr())
        assert first["status"] == "REVIEW_REQUIRED"
        assert first["blocked_gate"] == "G1"
        checklist = next(s["result"] for s in first["stages"] if s["stage"] == "headword_checklists")
        assert checklist["book_has_headword_checklists"] is True
        assert (checklist["pages_agreeing"], checklist["pages_disagreeing"]) == (5, 1)
        assert checklist["pages_without_checklist"] == 1

        tasks = {
            task.reason_code: task
            for task in db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id)
        }
        assert set(tasks) == {"HEADWORD_NOT_IN_CHECKLIST", "HEADWORD_PAGE_WITHOUT_CHECKLIST"}
        misread = tasks["HEADWORD_NOT_IN_CHECKLIST"]
        assert misread.source_context["headword_as_read"] == "GUE"
        assert misread.candidate_values == []  # "GUE" is too unlike "incur" to suggest

        resolve_review_task(
            db,
            misread.id,
            resolution={"decision": "ACCEPT", "corrected_text": "incur [ɪnˈkɜː] vt.招致，遭受"},
            reviewer_id="reviewer-1",
        )
        resolve_review_task(
            db,
            tasks["HEADWORD_PAGE_WITHOUT_CHECKLIST"].id,
            resolution={"decision": "ACCEPT", "classification": "NOT_AN_ENTRY_PAGE"},
            reviewer_id="reviewer-1",
        )

        second = run_pipeline(db, run_id, ocr_adapter=ScannedBookOcr())
        assert second["status"] == "COMPLETED"
        assert (
            db.query(ReviewTask)
            .filter(ReviewTask.processing_run_id == run_id, ReviewTask.status == "OPEN")
            .count()
            == 0
        )

        entries = {
            entry.lemma: entry
            for entry in db.query(VocabularyEntry).filter(
                VocabularyEntry.processing_run_id == run_id
            )
        }
        # No preface sample, no checklist rows, nothing lost.
        assert sorted(entries) == ["a", "c", "compose", "e", "fraud", "impart", "incur", "x"]

        def fields(lemma):
            return {
                field.field_type: field.text
                for field in db.query(VocabularyField).filter(
                    VocabularyField.vocabulary_entry_id == entries[lemma].id
                )
            }

        def ipa(lemma):
            return [
                item.ipa
                for item in db.query(Pronunciation).filter(
                    Pronunciation.vocabulary_entry_id == entries[lemma].id
                )
            ]

        # OCR IPA is kept as source text, never as a verified pronunciation…
        assert ipa("compose") == []
        assert fields("compose")["IPA_OCR_UNVERIFIED"] == "kampauz"
        # …unless a human confirmed the line.
        assert ipa("incur") == ["ɪnˈkɜː"]
        assert "IPA_OCR_UNVERIFIED" not in fields("incur")
        fraud = fields("fraud")
        assert fraud["EXAM_QUESTION"].startswith("Harold was a(n)")
        assert fraud["EXAM_EXPLANATION"] == "选D。alien：外侨"
        assert "continued from the previous page" in fraud["EXAMPLE"]
        checklist_rows = [
            block.raw_text
            for block in db.query(SourceBlock).filter(SourceBlock.processing_run_id == run_id)
            if (block.metadata_json or {}).get("role") == "HEADWORD_CHECKLIST"
        ]
        assert sorted(checklist_rows) == ["21 compose fraud", "a", "c", "e", "incur impart 22", "x"]
    finally:
        db.close()


class DisputedLineOcr(ScannedBookOcr):
    """The same book, with one example line the readers could not agree on."""

    def extract_page(self, page):
        result = super().extract_page(page)
        for block in result.blocks:
            disputed = "composed" in block.text
            block.metadata = {
                "consensus": {
                    "status": "DISPUTED" if disputed else "UNANIMOUS",
                    "readers": 3,
                    "disputes": [{"base": "o", "others": ["0", "a"]}] if disputed else [],
                    "other_readings": {},
                }
            }
            if disputed:
                block.confidence = 0.5
            elif "fraud[" in block.text:
                block.confidence = 0.6  # low engine score, yet confirmed by two readers
        return result


def test_unconfirmed_lines_are_parked_and_keep_their_entry_out_of_gold(client):
    run_id = _upload(client)
    db = SessionLocal()
    try:
        first = run_pipeline(db, run_id, ocr_adapter=DisputedLineOcr())
        assert first["blocked_gate"] == "G1"
        by_status: dict[str, list[ReviewTask]] = {}
        for task in db.query(ReviewTask).filter(ReviewTask.processing_run_id == run_id):
            by_status.setdefault(task.status, []).append(task)
        # The disputed line is parked; the confirmed low-score line raises nothing.
        assert [task.reason_code for task in by_status["DEFERRED"]] == ["OCR_READERS_DISAGREE"]
        assert {task.reason_code for task in by_status["OPEN"]} == {
            "HEADWORD_NOT_IN_CHECKLIST",
            "HEADWORD_PAGE_WITHOUT_CHECKLIST",
        }
        for task in by_status["OPEN"]:
            resolution = {"decision": "ACCEPT"}
            if task.target_entity_type == "Page":
                resolution["classification"] = "NOT_AN_ENTRY_PAGE"
            else:
                resolution["corrected_text"] = "incur[x]vt.招致"
            resolve_review_task(db, task.id, resolution=resolution, reviewer_id="reviewer-1")

        second = run_pipeline(db, run_id, ocr_adapter=DisputedLineOcr())
        assert (second["status"], second["blocked_gate"]) == ("REVIEW_REQUIRED", "G6")
        assert second["gate_result"]["metrics"]["unresolved_entries"] == 1
        assert second["gate_result"]["metrics"]["open_review_tasks"] == 0
        status = {
            entry.lemma: entry.verification_status
            for entry in db.query(VocabularyEntry).filter(
                VocabularyEntry.processing_run_id == run_id
            )
        }
        assert status["compose"] == "REVIEW_REQUIRED"
        assert status["fraud"] == "AUTO_VERIFIED"

        assert client.get(f"/api/v1/runs/{run_id}/gold").status_code == 409
        preview = client.get(f"/api/v1/runs/{run_id}/preview").json()
        assert preview["preview"] is True
        assert (preview["record_count"], preview["verified_record_count"]) == (8, 7)
        rows = {record["lemma"]: record["unconfirmed_ocr_rows"] for record in preview["records"]}
        assert rows["compose"] == 1 and rows["fraud"] == 0

        # A human settles the parked line with a corrected reading. The entries
        # were cut from the old text, so they are rebuilt from the corrected one.
        resolve_review_task(
            db,
            by_status["DEFERRED"][0].id,
            resolution={"decision": "ACCEPT", "corrected_text": "【例】A corrected example line."},
            reviewer_id="reviewer-1",
        )
        third = run_pipeline(db, run_id, ocr_adapter=DisputedLineOcr())
        assert third["status"] == "COMPLETED"
        segmentation = next(
            stage["result"] for stage in third["stages"] if stage["stage"] == "entry_segmentation"
        )
        assert (segmentation["reused"], segmentation["rebuilt"]) == (False, True)
        compose = (
            db.query(VocabularyEntry)
            .filter(VocabularyEntry.processing_run_id == run_id, VocabularyEntry.lemma == "compose")
            .one()
        )
        assert compose.verification_status == "AUTO_VERIFIED"
        example = (
            db.query(VocabularyField)
            .filter(
                VocabularyField.vocabulary_entry_id == compose.id,
                VocabularyField.field_type == "EXAMPLE",
            )
            .one()
        )
        assert example.text == "A corrected example line."
        assert (
            db.query(VocabularyEntry).filter(VocabularyEntry.processing_run_id == run_id).count()
            == 8
        )
        fourth = run_pipeline(db, run_id, ocr_adapter=DisputedLineOcr())
        reused = next(s["result"] for s in fourth["stages"] if s["stage"] == "entry_segmentation")
        assert reused["reused"] is True  # nothing changed since: no second rebuild
    finally:
        db.close()


def test_parked_lines_outside_every_entry_are_set_aside(client):
    class FrontMatterDispute(ScannedBookOcr):
        def extract_page(self, page):
            result = super().extract_page(page)
            for block in result.blocks:
                disputed = page.page_number == 1 and block.reading_order == 0
                block.metadata = {
                    "consensus": {
                        "status": "DISPUTED" if disputed else "UNANIMOUS",
                        "readers": 3,
                        "disputes": [{"base": "a", "others": ["b", "c"]}] if disputed else [],
                        "other_readings": {},
                    }
                }
            return result

    run_id = _upload(client)
    db = SessionLocal()
    try:
        run_pipeline(db, run_id, ocr_adapter=FrontMatterDispute())
        for task in db.query(ReviewTask).filter(
            ReviewTask.processing_run_id == run_id, ReviewTask.status == "OPEN"
        ):
            resolution = {"decision": "ACCEPT"}
            if task.target_entity_type == "Page":
                resolution["classification"] = "NOT_AN_ENTRY_PAGE"
            else:
                resolution["corrected_text"] = "incur[x]vt.招致"
            resolve_review_task(db, task.id, resolution=resolution, reviewer_id="reviewer-1")
        result = run_pipeline(db, run_id, ocr_adapter=FrontMatterDispute())
        # The disputed line sits on a page ruled not to hold entries.
        assert result["status"] == "COMPLETED"
        parked = (
            db.query(ReviewTask)
            .filter(
                ReviewTask.processing_run_id == run_id,
                ReviewTask.reason_code == "OCR_READERS_DISAGREE",
            )
            .one()
        )
        assert parked.status == "NOT_APPLICABLE"
    finally:
        db.close()
