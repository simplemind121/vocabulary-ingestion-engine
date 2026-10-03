import io
from pathlib import Path

import pytest

from app.snapshot_cli import (
    export_storage_snapshot,
    export_volume_snapshot,
    restore_storage_snapshot,
    restore_volume_snapshot,
)
from app.storage import LocalStorageAdapter


def test_object_storage_snapshot_replace_roundtrip(tmp_path):
    source = LocalStorageAdapter(tmp_path / "source")
    source.put_bytes("gold/词汇.json", b"verified")
    archive = io.BytesIO()

    result = export_storage_snapshot(source, archive)

    assert result == {"object_count": 1}
    destination = LocalStorageAdapter(tmp_path / "destination")
    destination.put_bytes("stale.txt", b"remove-me")
    archive.seek(0)
    restored = restore_storage_snapshot(destination, archive, replace=True)

    assert restored == {"object_count": 1}
    assert destination.list_keys() == ["gold/词汇.json"]
    assert destination.read_bytes("gold/词汇.json") == b"verified"


def test_application_volume_snapshot_replace_roundtrip(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "bronze").mkdir()
    (source / "bronze" / "source.pdf").write_bytes(b"source")
    archive = io.BytesIO()

    result = export_volume_snapshot(source, archive)

    assert result == {"file_count": 1}
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "stale.txt").write_text("remove-me")
    archive.seek(0)
    restored = restore_volume_snapshot(destination, archive, replace=True)

    assert restored == {"file_count": 1}
    assert sorted(path.relative_to(destination).as_posix() for path in destination.rglob("*")) == [
        "bronze",
        "bronze/source.pdf",
    ]
    assert (destination / "bronze" / "source.pdf").read_bytes() == b"source"


def test_volume_restore_rejects_unsafe_clear_root():
    with pytest.raises(ValueError, match="unsafe volume root"):
        restore_volume_snapshot(Path("/"), io.BytesIO(), replace=True)
