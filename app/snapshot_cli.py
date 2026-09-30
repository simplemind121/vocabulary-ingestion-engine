from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from app.settings import get_settings
from app.storage import StorageAdapter, build_storage_adapter

SNAPSHOT_SCHEMA = "vie.snapshot.v1"
_METADATA_NAME = "_vie/metadata.json"
_MANIFEST_NAME = "_vie/manifest.json"


def _tar_info(name: str, size: int, *, pax_headers: dict[str, str] | None = None) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o600
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.pax_headers = pax_headers or {}
    return info


def _add_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    archive.addfile(_tar_info(name, len(payload)), io.BytesIO(payload))


def _metadata(kind: str) -> bytes:
    return json.dumps(
        {"schema": SNAPSHOT_SCHEMA, "kind": kind},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def export_storage_snapshot(storage: StorageAdapter, output: BinaryIO) -> dict:
    manifest: list[dict] = []
    with tarfile.open(fileobj=output, mode="w|gz", format=tarfile.PAX_FORMAT) as archive:
        _add_bytes(archive, _METADATA_NAME, _metadata("object-storage"))
        for index, key in enumerate(storage.list_keys()):
            payload = storage.read_bytes(key)
            digest = hashlib.sha256(payload).hexdigest()
            archive.addfile(
                _tar_info(
                    f"objects/{index:08d}",
                    len(payload),
                    pax_headers={"VIE.key": key, "VIE.sha256": digest},
                ),
                io.BytesIO(payload),
            )
            manifest.append({"key": key, "byte_size": len(payload), "sha256": digest})
        manifest_payload = json.dumps(
            {"schema": SNAPSHOT_SCHEMA, "objects": manifest},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        _add_bytes(archive, _MANIFEST_NAME, manifest_payload)
    return {"object_count": len(manifest)}


def restore_storage_snapshot(storage: StorageAdapter, source: BinaryIO, *, replace: bool) -> dict:
    if replace:
        for key in storage.list_keys():
            storage.delete(key)

    restored: list[dict] = []
    metadata_seen = False
    manifest: dict | None = None
    with tarfile.open(fileobj=source, mode="r|gz") as archive:
        for member in archive:
            fileobj = archive.extractfile(member)
            if fileobj is None:
                continue
            payload = fileobj.read()
            if member.name == _METADATA_NAME:
                metadata = json.loads(payload)
                if metadata != {"schema": SNAPSHOT_SCHEMA, "kind": "object-storage"}:
                    raise ValueError("unsupported object storage snapshot")
                metadata_seen = True
                continue
            if member.name == _MANIFEST_NAME:
                manifest = json.loads(payload)
                continue
            if not member.name.startswith("objects/") or not metadata_seen:
                raise ValueError("invalid object storage snapshot member")
            key = member.pax_headers.get("VIE.key")
            expected_digest = member.pax_headers.get("VIE.sha256")
            actual_digest = hashlib.sha256(payload).hexdigest()
            if not key or expected_digest != actual_digest:
                raise ValueError(f"object snapshot integrity check failed: {member.name}")
            storage.put_bytes(key, payload)
            restored.append({"key": key, "byte_size": len(payload), "sha256": actual_digest})

    expected = {"schema": SNAPSHOT_SCHEMA, "objects": restored}
    if manifest != expected:
        raise ValueError("object storage snapshot manifest mismatch")
    return {"object_count": len(restored)}


def export_volume_snapshot(root: Path, output: BinaryIO) -> dict:
    root = root.resolve()
    manifest: list[dict] = []
    with tarfile.open(fileobj=output, mode="w|gz", format=tarfile.PAX_FORMAT) as archive:
        _add_bytes(archive, _METADATA_NAME, _metadata("application-volume"))
        files = sorted(
            path for path in root.rglob("*") if path.is_file() and not path.is_symlink()
        )
        for index, path in enumerate(files):
            relative = path.relative_to(root).as_posix()
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            with path.open("rb") as stream:
                archive.addfile(
                    _tar_info(
                        f"files/{index:08d}",
                        path.stat().st_size,
                        pax_headers={"VIE.path": relative, "VIE.sha256": digest.hexdigest()},
                    ),
                    stream,
                )
            manifest.append(
                {"path": relative, "byte_size": path.stat().st_size, "sha256": digest.hexdigest()}
            )
        manifest_payload = json.dumps(
            {"schema": SNAPSHOT_SCHEMA, "files": manifest},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        _add_bytes(archive, _MANIFEST_NAME, manifest_payload)
    return {"file_count": len(manifest)}


def _safe_volume_target(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not relative or ".." in pure.parts:
        raise ValueError(f"unsafe volume snapshot path: {relative!r}")
    target = (root / Path(*pure.parts)).resolve()
    if root not in target.parents:
        raise ValueError(f"volume snapshot path escapes root: {relative!r}")
    return target


def _clear_volume(root: Path) -> None:
    resolved = root.resolve()
    if resolved == Path(resolved.anchor) or len(resolved.parts) < 3:
        raise ValueError(f"refusing to clear unsafe volume root: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    for child in resolved.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)


def restore_volume_snapshot(root: Path, source: BinaryIO, *, replace: bool) -> dict:
    root = root.resolve()
    if replace:
        _clear_volume(root)
    root.mkdir(parents=True, exist_ok=True)

    restored: list[dict] = []
    metadata_seen = False
    manifest: dict | None = None
    with tarfile.open(fileobj=source, mode="r|gz") as archive:
        for member in archive:
            fileobj = archive.extractfile(member)
            if fileobj is None:
                continue
            if member.name == _METADATA_NAME:
                metadata = json.loads(fileobj.read())
                if metadata != {"schema": SNAPSHOT_SCHEMA, "kind": "application-volume"}:
                    raise ValueError("unsupported application volume snapshot")
                metadata_seen = True
                continue
            if member.name == _MANIFEST_NAME:
                manifest = json.loads(fileobj.read())
                continue
            if not member.name.startswith("files/") or not metadata_seen:
                raise ValueError("invalid application volume snapshot member")
            relative = member.pax_headers.get("VIE.path")
            expected_digest = member.pax_headers.get("VIE.sha256")
            if not relative or not expected_digest:
                raise ValueError(f"missing volume snapshot metadata: {member.name}")
            target = _safe_volume_target(root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            byte_size = 0
            with target.open("wb") as output:
                while chunk := fileobj.read(1024 * 1024):
                    digest.update(chunk)
                    byte_size += len(chunk)
                    output.write(chunk)
            if digest.hexdigest() != expected_digest:
                target.unlink(missing_ok=True)
                raise ValueError(f"volume snapshot integrity check failed: {relative}")
            restored.append(
                {"path": relative, "byte_size": byte_size, "sha256": digest.hexdigest()}
            )

    expected = {"schema": SNAPSHOT_SCHEMA, "files": restored}
    if manifest != expected:
        raise ValueError("application volume snapshot manifest mismatch")
    return {"file_count": len(restored)}


def _open_binary(path: str, mode: str) -> tuple[BinaryIO, bool]:
    if path == "-":
        return (sys.stdout.buffer if "w" in mode else sys.stdin.buffer), False
    return Path(path).open(mode), True


def main() -> int:
    parser = argparse.ArgumentParser(description="Export or restore VIE snapshot archives")
    parser.add_argument(
        "operation",
        choices=("storage-export", "storage-restore", "volume-export", "volume-restore"),
    )
    parser.add_argument("--file", default="-", help="archive path, or - for stdin/stdout")
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    if args.replace and os.getenv("VIE_ALLOW_DESTRUCTIVE_RESTORE") != "1":
        parser.error("--replace requires VIE_ALLOW_DESTRUCTIVE_RESTORE=1")

    exporting = args.operation.endswith("export")
    stream, should_close = _open_binary(args.file, "wb" if exporting else "rb")
    try:
        if args.operation == "storage-export":
            export_storage_snapshot(build_storage_adapter(get_settings()), stream)
        elif args.operation == "storage-restore":
            restore_storage_snapshot(
                build_storage_adapter(get_settings()), stream, replace=args.replace
            )
        elif args.operation == "volume-export":
            export_volume_snapshot(args.root, stream)
        else:
            restore_volume_snapshot(args.root, stream, replace=args.replace)
    finally:
        if should_close:
            stream.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
