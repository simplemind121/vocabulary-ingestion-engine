from __future__ import annotations

from typing import Any


_REQUIRED_IDENTITY_FIELDS = ("document_sha256", "page_number", "page_image_sha256")
_ALLOWED_PAYLOAD_FIELDS = ("blocks", "entries", "vocabulary")


def build_gold_prediction(
    scaffold: dict[str, Any],
    *,
    blocks: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    vocabulary: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a machine prediction bound to one frozen Gold page identity.

    This is intentionally a transport/identity contract only. It does not promote
    machine output to verified truth and does not enrich missing source content.
    """
    prediction = {field: scaffold.get(field) for field in _REQUIRED_IDENTITY_FIELDS}
    prediction.update(
        {
            "blocks": _require_dict_list(blocks, field="blocks"),
            "entries": _require_dict_list(entries, field="entries"),
            "vocabulary": _require_dict_list(vocabulary, field="vocabulary"),
        }
    )
    validate_gold_prediction(prediction)
    return prediction


def validate_gold_prediction(prediction: dict[str, Any]) -> None:
    """Fail closed when a Gold machine prediction is not source-identity bound."""
    document_sha = prediction.get("document_sha256")
    if not isinstance(document_sha, str) or len(document_sha) != 64:
        raise ValueError("prediction_document_sha256_required")

    page = prediction.get("page_number")
    if not isinstance(page, int) or page < 1:
        raise ValueError("prediction_page_number_required")

    page_sha = prediction.get("page_image_sha256")
    if not isinstance(page_sha, str) or len(page_sha) != 64:
        raise ValueError("prediction_page_image_sha256_required")

    for field in _ALLOWED_PAYLOAD_FIELDS:
        _require_dict_list(prediction.get(field), field=field)


def _require_dict_list(value: Any, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError(f"prediction_{field}_must_be_list")
    if any(not isinstance(item, dict) for item in value):
        raise TypeError(f"prediction_{field}_items_must_be_objects")
    return [dict(item) for item in value]
