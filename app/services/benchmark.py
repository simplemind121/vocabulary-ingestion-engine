from __future__ import annotations

from collections import Counter
from typing import Any


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _f1(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def benchmark_ocr(predicted_blocks: list[dict[str, Any]], truth_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    predicted = Counter(_norm(item.get("text")) for item in predicted_blocks if _norm(item.get("text")))
    truth = Counter(_norm(item.get("text")) for item in truth_blocks if _norm(item.get("text")))
    tp = sum((predicted & truth).values())
    fp = sum(predicted.values()) - tp
    fn = sum(truth.values()) - tp
    metrics = _f1(tp, fp, fn)
    exact = tp == sum(predicted.values()) == sum(truth.values())
    return {"layer": "OCR_BLOCK", "exact_match": exact, "tp": tp, "fp": fp, "fn": fn, **metrics}


def benchmark_entries(predicted_entries: list[dict[str, Any]], truth_entries: list[dict[str, Any]]) -> dict[str, Any]:
    def key(item: dict[str, Any]) -> tuple[str, str]:
        return (_norm(item.get("lemma")), _norm(item.get("raw_text")))

    predicted = Counter(key(item) for item in predicted_entries)
    truth = Counter(key(item) for item in truth_entries)
    tp = sum((predicted & truth).values())
    fp = sum(predicted.values()) - tp
    fn = sum(truth.values()) - tp
    metrics = _f1(tp, fp, fn)
    return {"layer": "ENTRY_SEGMENTATION", "exact_match": fp == 0 and fn == 0, "tp": tp, "fp": fp, "fn": fn, **metrics}


def benchmark_canonical(predicted: list[dict[str, Any]], truth: list[dict[str, Any]]) -> dict[str, Any]:
    fields = ("lemma", "display_form", "ipa", "part_of_speech", "definition")
    truth_by_lemma = {_norm(item.get("lemma")): item for item in truth if _norm(item.get("lemma"))}
    predicted_by_lemma = {_norm(item.get("lemma")): item for item in predicted if _norm(item.get("lemma"))}
    field_results: dict[str, dict[str, Any]] = {}
    total_correct = 0
    total_expected = 0

    for field in fields:
        correct = 0
        expected = 0
        for lemma, truth_item in truth_by_lemma.items():
            truth_value = _norm(truth_item.get(field))
            if not truth_value:
                continue
            expected += 1
            predicted_item = predicted_by_lemma.get(lemma, {})
            if _norm(predicted_item.get(field)) == truth_value:
                correct += 1
        field_results[field] = {"correct": correct, "expected": expected, "accuracy": correct / expected if expected else 1.0}
        total_correct += correct
        total_expected += expected

    missing_lemmas = sorted(set(truth_by_lemma) - set(predicted_by_lemma))
    unexpected_lemmas = sorted(set(predicted_by_lemma) - set(truth_by_lemma))
    return {
        "layer": "CANONICAL_EXTRACTION",
        "exact_match": total_correct == total_expected and not missing_lemmas and not unexpected_lemmas,
        "field_accuracy": total_correct / total_expected if total_expected else 1.0,
        "fields": field_results,
        "missing_lemmas": missing_lemmas,
        "unexpected_lemmas": unexpected_lemmas,
    }


def run_gold_benchmark(prediction: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
    ocr = benchmark_ocr(prediction.get("blocks", []), ground_truth.get("blocks", []))
    entries = benchmark_entries(prediction.get("entries", []), ground_truth.get("entries", []))
    canonical = benchmark_canonical(prediction.get("vocabulary", []), ground_truth.get("vocabulary", []))
    exact = bool(ocr["exact_match"] and entries["exact_match"] and canonical["exact_match"])
    return {
        "benchmark_schema_version": "1.0",
        "status": "PASS" if exact else "FAIL",
        "exact_match": exact,
        "layers": {"ocr": ocr, "segmentation": entries, "canonical": canonical},
    }
