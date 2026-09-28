from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol


class StorageAdapter(Protocol):
    provider: str

    def put_bytes(self, key: str, payload: bytes) -> dict:
        ...

    def read_bytes(self, key: str) -> bytes:
        ...

    def exists(self, key: str) -> bool:
        ...


class LocalStorageAdapter:
    provider = "local"

    def __init__(self, root: str | Path = "data") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        root = self.root.resolve()
        if root not in path.parents and path != root:
            raise ValueError("storage key escapes configured root")
        return path

    def put_bytes(self, key: str, payload: bytes) -> dict:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return {
            "provider": self.provider,
            "object_key": key,
            "byte_size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()
