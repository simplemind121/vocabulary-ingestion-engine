from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import GateEvaluation, GoldRelease, ProcessingRun, ReviewTask

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, sort_keys=True, default=str))


def render_metrics(db: Session, *, version: str) -> str:
    lines = [
        "# HELP vie_build_info Application build information.",
        "# TYPE vie_build_info gauge",
        f'vie_build_info{{version="{_escape_label(version)}"}} 1',
        "# HELP vie_processing_runs Current processing runs by status.",
        "# TYPE vie_processing_runs gauge",
    ]
    for status, count in _grouped_counts(db, ProcessingRun, ProcessingRun.status):
        lines.append(f'vie_processing_runs{{status="{_escape_label(status)}"}} {count}')

    lines.extend(
        [
            "# HELP vie_review_tasks Current review tasks by status.",
            "# TYPE vie_review_tasks gauge",
        ]
    )
    for status, count in _grouped_counts(db, ReviewTask, ReviewTask.status):
        lines.append(f'vie_review_tasks{{status="{_escape_label(status)}"}} {count}')

    lines.extend(
        [
            "# HELP vie_gate_evaluations Gate evaluations by Gate and status.",
            "# TYPE vie_gate_evaluations gauge",
        ]
    )
    gate_counts = (
        db.query(GateEvaluation.gate, GateEvaluation.status, func.count(GateEvaluation.id))
        .group_by(GateEvaluation.gate, GateEvaluation.status)
        .order_by(GateEvaluation.gate, GateEvaluation.status)
        .all()
    )
    for gate, status, count in gate_counts:
        lines.append(
            "vie_gate_evaluations"
            f'{{gate="{_escape_label(gate)}",status="{_escape_label(status)}"}} {count}'
        )

    release_count = db.query(func.count(GoldRelease.id)).scalar() or 0
    lines.extend(
        [
            "# HELP vie_gold_releases_total Gold releases persisted in this deployment.",
            "# TYPE vie_gold_releases_total gauge",
            f"vie_gold_releases_total {release_count}",
        ]
    )
    return "\n".join(lines) + "\n"


def _grouped_counts(db: Session, model: type, column: Any) -> list[tuple[str, int]]:
    rows = (
        db.query(column, func.count(model.id))
        .group_by(column)
        .order_by(column)
        .all()
    )
    return [(str(value), int(count)) for value, count in rows]


def _escape_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
