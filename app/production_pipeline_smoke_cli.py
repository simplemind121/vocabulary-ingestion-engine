from __future__ import annotations

import json
import time
import urllib.request
from uuid import uuid4

import fitz

from app.settings import get_settings


def main() -> int:
    api_key = get_settings().api_key
    if api_key is None:
        raise RuntimeError("VIE_API_KEY is required for the production pipeline smoke")
    headers = {"Authorization": f"Bearer {api_key.get_secret_value()}"}
    source = _sample_pdf()
    boundary = f"vie-smoke-{uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="worker-smoke.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + source + f"\r\n--{boundary}--\r\n".encode()
    upload = _request(
        "/api/v1/documents",
        method="POST",
        data=body,
        headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    run_id = upload["run_id"]
    queued = _request(
        f"/api/v1/runs/{run_id}/enqueue",
        method="POST",
        data=b"",
        headers=headers,
    )
    if queued.get("status") != "QUEUED" or not queued.get("task_id"):
        raise RuntimeError(f"pipeline did not queue: {queued}")

    deadline = time.monotonic() + 90
    result = {}
    while time.monotonic() < deadline:
        result = _request(f"/api/v1/runs/{run_id}", headers=headers)
        if result.get("status") not in {"QUEUED", "STARTING", "RUNNING"}:
            break
        time.sleep(0.5)
    if result.get("status") != "COMPLETED":
        raise RuntimeError(f"queued pipeline did not complete: {result}")
    gates = {item["gate"]: item["status"] for item in result.get("gates", [])}
    if any(gates.get(f"G{number}") != "PASS" for number in range(7)):
        raise RuntimeError(f"queued pipeline Gates did not all pass: {gates}")
    if not (result.get("metrics") or {}).get("gold_release_id"):
        raise RuntimeError("queued pipeline did not publish its verified Gold artifact")

    release_id = result["metrics"]["gold_release_id"]
    release = _request(f"/api/v1/gold/releases/{release_id}", headers=headers)
    if release.get("record_count") != 1:
        raise RuntimeError(f"unexpected Gold release metadata: {release}")
    exports = {
        artifact_format: _request_bytes(
            f"/api/v1/gold/releases/{release_id}/download/{artifact_format}",
            headers=headers,
        )
        for artifact_format in ("json", "csv", "xlsx")
    }
    exported_json = json.loads(exports["json"])
    if exported_json.get("record_count") != 1:
        raise RuntimeError("downloaded Gold JSON has the wrong record count")
    if not exports["csv"].startswith(b"id,lemma,language,verification_status"):
        raise RuntimeError("downloaded Gold CSV has the wrong header")
    if not exports["xlsx"].startswith(b"PK"):
        raise RuntimeError("downloaded Gold XLSX is not an XLSX archive")

    review_source = _scanned_review_pdf()
    review_boundary = f"vie-review-smoke-{uuid4().hex}"
    review_body = (
        f"--{review_boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="review-smoke.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + review_source + f"\r\n--{review_boundary}--\r\n".encode()
    review_upload = _request(
        "/api/v1/documents",
        method="POST",
        data=review_body,
        headers={
            **headers,
            "Content-Type": f"multipart/form-data; boundary={review_boundary}",
        },
    )
    review_run_id = review_upload["run_id"]
    review_queue = _request(
        f"/api/v1/runs/{review_run_id}/enqueue",
        method="POST",
        data=b"",
        headers=headers,
    )
    if review_queue.get("status") != "QUEUED":
        raise RuntimeError(f"review pipeline did not queue: {review_queue}")
    review_result = _wait_for_run(review_run_id, headers=headers)
    if review_result.get("status") != "REVIEW_REQUIRED":
        raise RuntimeError(f"review pipeline did not stop for review: {review_result}")
    reviews = _request(
        f"/api/v1/runs/{review_run_id}/reviews?status=OPEN",
        headers=headers,
    )
    if reviews.get("count", 0) < 1:
        raise RuntimeError("review pipeline did not create an open review task")
    ordered_reviews = sorted(
        reviews["items"],
        key=lambda item: (
            (item.get("bbox") or {}).get("y1", 0),
            (item.get("bbox") or {}).get("x1", 0),
        ),
    )
    for index, review in enumerate(ordered_reviews):
        if review.get("target_entity_type") != "SourceBlock":
            raise RuntimeError(f"unexpected production review target: {review}")
        resolution_body = {
            "reviewer_id": "production-smoke-reviewer",
            "decision": "ACCEPT" if index == 0 else "DISCARD",
            "notes": "Production smoke review verified against the rendered source page.",
        }
        if index == 0:
            resolution_body["corrected_text"] = "review* [rɪˈvjuː]\nn. examination"
        resolution = json.dumps(resolution_body).encode()
        resolved = _request(
            f"/api/v1/reviews/{review['id']}/resolve",
            method="POST",
            data=resolution,
            headers={**headers, "Content-Type": "application/json"},
        )
        if resolved.get("status") != "RESOLVED":
            raise RuntimeError(f"production review did not resolve: {resolved}")
    _request(
        f"/api/v1/runs/{review_run_id}/enqueue",
        method="POST",
        data=b"",
        headers=headers,
    )
    reviewed_result = _wait_for_run(review_run_id, headers=headers)
    if reviewed_result.get("status") != "COMPLETED":
        raise RuntimeError(f"reviewed pipeline did not complete: {reviewed_result}")

    print(
        json.dumps(
            {
                "status": "PASS",
                "run_id": run_id,
                "task_id": queued["task_id"],
                "gates": gates,
                "exports": sorted(exports),
                "review_run_id": review_run_id,
                "resolved_reviews": reviews["count"],
            },
            sort_keys=True,
        )
    )
    return 0


def _request(
    path: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str],
) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:8000{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _request_bytes(path: str, *, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(
        f"http://127.0.0.1:8000{path}",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _wait_for_run(run_id: str, *, headers: dict[str, str]) -> dict:
    deadline = time.monotonic() + 90
    result = {}
    while time.monotonic() < deadline:
        result = _request(f"/api/v1/runs/{run_id}", headers=headers)
        if result.get("status") not in {"QUEUED", "STARTING", "RUNNING"}:
            return result
        time.sleep(0.5)
    return result


def _sample_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "abandon* [əˈbændən] v. to leave permanently")
    payload = document.tobytes()
    document.close()
    return payload


def _scanned_review_pdf() -> bytes:
    source = fitz.open()
    page = source.new_page()
    page.insert_text((72, 100), "review* [review]", fontsize=28)
    page.insert_text((72, 150), "n. examination", fontsize=28)
    image = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png")
    source.close()

    scanned = fitz.open()
    page = scanned.new_page()
    page.insert_image(page.rect, stream=image)
    payload = scanned.tobytes()
    scanned.close()
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
