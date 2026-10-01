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
    print(
        json.dumps(
            {
                "status": "PASS",
                "run_id": run_id,
                "task_id": queued["task_id"],
                "gates": gates,
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


def _sample_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "abandon* [əˈbændən] v. to leave permanently")
    payload = document.tobytes()
    document.close()
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
