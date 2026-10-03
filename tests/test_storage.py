import io

from app.storage import LocalStorageAdapter, S3StorageAdapter


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


class FakeS3Client:
    def __init__(self):
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"ResponseMetadata": {"HTTPStatusCode": 404}, "Error": {}},
                "HeadObject",
            )

    def head_bucket(self, *, Bucket):
        return {"Bucket": Bucket}

    def list_objects_v2(self, *, Bucket, ContinuationToken=None):
        assert ContinuationToken is None
        return {
            "Contents": [
                {"Key": key}
                for bucket, key in self.objects
                if bucket == Bucket
            ],
            "IsTruncated": False,
        }

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


def test_s3_storage_roundtrip_and_healthcheck():
    client = FakeS3Client()
    storage = S3StorageAdapter(bucket="artifacts", client=client)

    result = storage.put_bytes("gold/release.json", b"verified")

    assert result["provider"] == "s3"
    assert result["bucket"] == "artifacts"
    assert storage.exists("gold/release.json")
    assert not storage.exists("gold/missing.json")
    assert storage.read_bytes("gold/release.json") == b"verified"
    assert storage.healthcheck() is True
    assert storage.list_keys() == ["gold/release.json"]
    storage.delete("gold/release.json")
    assert not storage.exists("gold/release.json")
