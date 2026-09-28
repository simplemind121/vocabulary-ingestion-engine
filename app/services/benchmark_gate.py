from __future__ import annotations

from typing import Any


DEFAULT_THRESHOLDS = {
    "ocr_f1": 1.0,
    "segmentation_f1": 1.0,
    "canonical_field_accuracy": 1.0,
}


def evaluate_benchmark_gate(
    report: dict[str, Any],
    *,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Convert a benchmark report into a deterministic CI gate decision.

    Gold Sample v1 is deliberately strict: unless explicitly overridden, every
    benchmark layer must be exact and all aggregate metrics must equal 1.0.
    """
    required = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    layers = report.get("layers") or {}
    ocr = layers.get("ocr") or {}
    segmentation = layers.get("segmentation") or {}
    canonical = layers.get("canonical") or {}

    observed = {
        "ocr_f1": float(ocr.get("f1", 0.0)),
        "segmentation_f1": float(segmentation.get("f1", 0.0)),
        "canonical_field_accuracy": float(canonical.get("field_accuracy", 0.0)),
    }
    failures = [
        metric
        for metric, minimum in required.items()
        if observed.get(metric, 0.0) < minimum
    ]

    if not bool(report.get("exact_match")):
        failures.append("exact_match")

    failures = sorted(set(failures))
    return {
        "gate": "GOLD_REGRESSION",
        "status": "PASS" if not failures else "FAIL",
        "publish_allowed": not failures,
        "thresholds": required,
        "observed": observed,
        "blocking_failures": failures,
    }


def assert_benchmark_gate(report: dict[str, Any]) -> dict[str, Any]:
    result = evaluate_benchmark_gate(report)
    if result["status"] != "PASS":
        failures = ", ".join(result["blocking_failures"])
        raise RuntimeError(f"Gold benchmark regression gate failed: {failures}")
    return result
