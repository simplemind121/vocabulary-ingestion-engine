def test_console_is_served_at_root_without_embedding_secrets(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "VIE 控制台" in response.text
    for path in (
        "/api/v1/runs",
        "/api/v1/documents",
        "/enqueue",
        "/source-media",
        "/gold/releases/",
        "/resolve",
    ):
        assert path in response.text
    assert "Bearer ${S.token}" in response.text


def test_run_listing_reports_newest_first_with_open_reviews(client, sample_pdf_bytes):
    first = client.post(
        "/api/v1/documents", files={"file": ("first.pdf", sample_pdf_bytes, "application/pdf")}
    ).json()
    second = client.post(
        "/api/v1/documents", files={"file": ("second.pdf", sample_pdf_bytes, "application/pdf")}
    ).json()
    client.post(f"/api/v1/runs/{second['run_id']}/execute")

    items = client.get("/api/v1/runs?limit=2").json()["items"]

    assert [item["id"] for item in items] == [second["run_id"], first["run_id"]]
    assert items[0]["filename"] == "second.pdf"
    assert items[0]["status"] == "COMPLETED"
    assert items[0]["gold_release_id"]
    assert items[0]["page_count"] == 1
    assert items[0]["open_reviews"] == 0
    assert items[1]["status"] == "READY"
    assert items[1]["gold_release_id"] is None
    assert client.get("/api/v1/runs?limit=0").status_code == 422
