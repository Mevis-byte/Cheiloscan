"""Unit tests for the Vercel Blob asset store (no network access)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from vercel.blob.errors import BlobNotFoundError
from vercel.blob.models import BlobPrefix, HeadResult, ListBlob

from cheiloscan.storage import blob_store
from cheiloscan.storage.base import StorageError
from cheiloscan.storage.blob_store import VercelBlobAssetStore


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"opaque-research-bytes"
WEBP_BYTES = b"RIFF0000WEBP" + b"opaque-research-bytes"


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test_secret")
    return VercelBlobAssetStore(prefix="research/dev", access="private")


def _head(size: int) -> HeadResult:
    return HeadResult(
        url="https://blob.example/asset",
        download_url="https://blob.example/asset?download=1",
        pathname="research/dev/original/ab/asset.png",
        size=size,
        etag="etag",
        uploaded_at=datetime.now(timezone.utc),
        content_type="image/png",
        content_disposition="attachment",
        cache_control="public, max-age=0",
    )


def _listed(pathname: str, size: int) -> ListBlob:
    return ListBlob(
        url="https://blob.example/asset",
        download_url="https://blob.example/asset?download=1",
        pathname=pathname,
        size=size,
        uploaded_at=datetime.now(timezone.utc),
        etag="etag",
    )


def test_credentials_are_required(monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("VERCEL_BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("BLOB_STORE_ID", raising=False)
    with pytest.raises(StorageError, match="credentials"):
        VercelBlobAssetStore()


def test_save_original_is_content_addressed_and_private(store, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(blob_store, "head_blob", lambda key: (_ for _ in ()).throw(BlobNotFoundError("missing")))
    monkeypatch.setattr(
        blob_store,
        "put_blob",
        lambda key, body, **kwargs: calls.append((key, body, kwargs)),
    )

    stored = store.save_original(PNG_BYTES, "png")

    assert stored.created is True
    assert stored.size_bytes == len(PNG_BYTES)
    expected = (
        f"research/dev/original/{stored.sha256[:2]}/{stored.sha256}.png"
    )
    assert stored.relative_path == expected.removeprefix("research/dev/")
    assert calls[0][0] == expected
    assert calls[0][1] == PNG_BYTES
    assert calls[0][2] == {
        "access": "private",
        "content_type": "image/png",
        "allow_overwrite": False,
    }


def test_existing_original_is_deduplicated(store, monkeypatch):
    monkeypatch.setattr(blob_store, "head_blob", lambda key: _head(len(PNG_BYTES)))

    def unexpected_put(*args, **kwargs):
        raise AssertionError("an existing original must not be overwritten")

    monkeypatch.setattr(blob_store, "put_blob", unexpected_put)
    stored = store.save_original(PNG_BYTES, "png")
    assert stored.created is False


def test_original_size_mismatch_refuses_overwrite(store, monkeypatch):
    monkeypatch.setattr(blob_store, "head_blob", lambda key: _head(len(PNG_BYTES) + 1))
    with pytest.raises(StorageError, match="refusing to overwrite"):
        store.save_original(PNG_BYTES, "png")


def test_save_derived_uses_run_scoped_key(store, monkeypatch):
    keys: list[str] = []
    monkeypatch.setattr(
        blob_store,
        "put_blob",
        lambda key, body, **kwargs: keys.append(key),
    )
    stored = store.save_derived(
        WEBP_BYTES, run_id="run-123", role="final", image_format="webp"
    )
    assert keys == ["research/dev/derived/run-123/final.webp"]
    assert stored.relative_path == "derived/run-123/final.webp"


def test_reads_are_streamed_and_missing_objects_raise(store, monkeypatch):
    monkeypatch.setattr(
        blob_store,
        "get_blob",
        lambda key, *, access: SimpleNamespace(body=PNG_BYTES),
    )
    monkeypatch.setattr(
        blob_store,
        "stream_blob",
        lambda key, *, access: _stream([PNG_BYTES[:8], PNG_BYTES[8:]]),
    )
    key = store._key("original/ab/asset.png")
    assert store.read(key.removeprefix("research/dev/")) == PNG_BYTES
    assert b"".join(store.iter_read(key.removeprefix("research/dev/"))) == PNG_BYTES

    def missing(*args, **kwargs):
        raise BlobNotFoundError("missing")

    monkeypatch.setattr(blob_store, "head_blob", missing)
    monkeypatch.setattr(blob_store, "get_blob", missing)
    monkeypatch.setattr(blob_store, "stream_blob", missing)
    assert store.exists("original/ab/missing.png") is False
    with pytest.raises(FileNotFoundError):
        store.read("original/ab/missing.png")
    with pytest.raises(FileNotFoundError):
        list(store.iter_read("original/ab/missing.png"))


class _Stream:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    def __enter__(self):
        return iter(self.chunks)

    def __exit__(self, *args) -> None:
        return None


def _stream(chunks: list[bytes]):
    return _Stream(chunks)


def test_delete_derived_run_removes_only_blob_entries(store, monkeypatch):
    deleted: list[list[str]] = []
    monkeypatch.setattr(
        blob_store,
        "query_blob_entries",
        lambda *, prefix: [
            _listed("research/dev/derived/run-123/final.png", 10),
            BlobPrefix(prefix="research/dev/derived/run-123/sub/"),
        ],
    )
    monkeypatch.setattr(blob_store, "delete_blob", lambda keys: deleted.append(list(keys)))

    store.delete_derived_run("run-123")
    assert deleted == [["research/dev/derived/run-123/final.png"]]


def test_describe_reports_real_blob_usage(store, monkeypatch):
    monkeypatch.setattr(
        blob_store,
        "query_blob_entries",
        lambda *, prefix: [
            _listed("research/dev/original/aa/one.png", 10),
            _listed("research/dev/derived/run/two.png", 15),
            BlobPrefix(prefix="research/dev/derived/run/"),
        ],
    )
    report = store.describe()
    assert report["backend"] == "vercel_blob"
    assert report["available"] is True
    assert report["bytes_used"] == 25


def test_unsafe_paths_are_rejected(store):
    with pytest.raises(StorageError):
        store.read("../secret.png")
    with pytest.raises(StorageError):
        store.save_derived(PNG_BYTES, run_id="../escape", role="final", image_format="png")
