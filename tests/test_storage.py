from app.storage import LocalStorageAdapter


def test_local_storage_roundtrip(tmp_path):
    storage = LocalStorageAdapter(tmp_path)
    result = storage.put_bytes("bronze/example.bin", b"hello")
    assert result["byte_size"] == 5
    assert storage.exists("bronze/example.bin")
    assert storage.read_bytes("bronze/example.bin") == b"hello"


def test_local_storage_rejects_path_escape(tmp_path):
    storage = LocalStorageAdapter(tmp_path)
    try:
        storage.put_bytes("../escape.bin", b"x")
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal must be rejected")
