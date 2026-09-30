from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

import boto3
from botocore.exceptions import ClientError

from app.settings import Settings


class StorageAdapter(Protocol):
    provider: str

    def put_bytes(self, key: str, payload: bytes) -> dict:
        ...

    def read_bytes(self, key: str) -> bytes:
        ...

    def exists(self, key: str) -> bool:
        ...

    def healthcheck(self) -> bool:
        ...

    def list_keys(self) -> list[str]:
        ...

    def delete(self, key: str) -> None:
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
            "bucket": "local",
            "object_key": key,
            "byte_size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def healthcheck(self) -> bool:
        return self.root.is_dir()

    def list_keys(self) -> list[str]:
        root = self.root.resolve()
        return sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        )

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3StorageAdapter:
    provider = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region: str = "us-east-1",
        client=None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket is required")
        self.bucket = bucket
        self._client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )

    def put_bytes(self, key: str, payload: bytes) -> dict:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=payload)
        return {
            "provider": self.provider,
            "bucket": self.bucket,
            "object_key": key,
            "byte_size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def read_bytes(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                return False
            raise

    def healthcheck(self) -> bool:
        self._client.head_bucket(Bucket=self.bucket)
        return True

    def list_keys(self) -> list[str]:
        keys: list[str] = []
        continuation_token: str | None = None
        while True:
            request = {"Bucket": self.bucket}
            if continuation_token is not None:
                request["ContinuationToken"] = continuation_token
            response = self._client.list_objects_v2(**request)
            keys.extend(item["Key"] for item in response.get("Contents", []))
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")
            if not continuation_token:
                raise RuntimeError("S3 listing was truncated without a continuation token")
        return sorted(keys)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)


def build_storage_adapter(settings: Settings) -> StorageAdapter:
    backend = settings.storage_backend.strip().lower()
    if backend == "local":
        return LocalStorageAdapter(settings.storage_root)
    if backend in {"s3", "minio"}:
        if not settings.s3_access_key_id or not settings.s3_secret_access_key:
            raise ValueError("S3 credentials are required")
        return S3StorageAdapter(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            region=settings.s3_region,
        )
    raise ValueError(f"unsupported storage backend: {settings.storage_backend}")
