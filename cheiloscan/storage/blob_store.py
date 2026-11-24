"""Content-addressed asset store backed by Vercel Blob.

This backend implements the same contract as the local
:class:`~cheiloscan.storage.asset_store.AssetStore` but keeps no durable local
state, which is required on Vercel Functions. Object keys mirror the local
layout under an optional prefix::

    <prefix>/original/<aa>/<sha256>.<ext>
    <prefix>/derived/<run_id>/<role>.<ext>

Content-addressing still prevents accidental original replacement: a key is
only written once (``allow_overwrite=False``) and its existence is checked with
a HEAD request before upload. Reads are streamed so image responses stay below
Vercel's buffered response-body limit.
"""

from __future__ import annotations

import os
from typing import Iterator, Literal

from vercel.blob.errors import BlobError, BlobNotFoundError
from vercel.blob.models import ListBlob
from vercel.blob.sync import (
    delete_blob,
    get_blob,
    head_blob,
    put_blob,
    query_blob_entries,
    stream_blob,
)

from .base import (
    AssetStoreLike,
    StorageError,
    StoredFile,
    validate_component,
    validate_relative_path,
)
from ..util.imageio import MIME_TYPES, STORAGE_EXTENSIONS, sha256_hex

__all__ = ["VercelBlobAssetStore"]


class VercelBlobAssetStore(AssetStoreLike):
    """Store originals and derived images in Vercel Blob."""

    def __init__(
        self,
        prefix: str = "cheiloscan",
        access: Literal["public", "private"] = "private",
    ) -> None:
        if access not in {"public", "private"}:
            raise StorageError(f"invalid blob access mode: {access!r}")
        self.prefix = self._normalize_prefix(prefix)
        self.access: Literal["public", "private"] = access
        if not (
            os.environ.get("BLOB_READ_WRITE_TOKEN")
            or os.environ.get("VERCEL_BLOB_READ_WRITE_TOKEN")
            or os.environ.get("BLOB_STORE_ID")
        ):
            raise StorageError(
                "Vercel Blob credentials are not configured; set "
                "BLOB_READ_WRITE_TOKEN or BLOB_STORE_ID"
            )

    # ---------------------------------------------------------------- paths

    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        cleaned = prefix.strip().strip("/")
        if not cleaned:
            return ""
        for part in cleaned.split("/"):
            validate_component(part, label="storage prefix")
        return cleaned

    def _key(self, relative_path: str) -> str:
        relative = validate_relative_path(relative_path)
        return f"{self.prefix}/{relative}" if self.prefix else relative

    def _root_prefix(self) -> str:
        return f"{self.prefix}/" if self.prefix else ""

    @staticmethod
    def _error(_exc: BaseException) -> StorageError:
        """Hide SDK/credential details; callers attach the original cause."""
        return StorageError("a Vercel Blob operation failed")

    # ------------------------------------------------------------ originals

    def save_original(self, data: bytes, image_format: str) -> StoredFile:
        """Persist immutable original bytes, deduplicating by content hash."""
        if image_format not in STORAGE_EXTENSIONS:
            raise StorageError(f"unsupported image format: {image_format!r}")
        if not data:
            raise StorageError("refusing to store an empty original")

        digest = sha256_hex(data)
        extension = STORAGE_EXTENSIONS[image_format]
        relative = f"original/{digest[:2]}/{digest}.{extension}"
        key = self._key(relative)

        try:
            existing = head_blob(key)
        except BlobNotFoundError:
            existing = None
        except BlobError as exc:
            raise self._error(exc) from exc

        if existing is not None:
            if int(existing.size) != len(data):
                raise StorageError(
                    "stored original does not match its content address; "
                    "refusing to overwrite"
                )
            return StoredFile(
                relative_path=relative,
                sha256=digest,
                size_bytes=len(data),
                created=False,
            )

        try:
            put_blob(
                key,
                data,
                access=self.access,
                content_type=MIME_TYPES.get(image_format, "application/octet-stream"),
                allow_overwrite=False,
            )
        except BlobError as exc:
            raise self._error(exc) from exc
        return StoredFile(
            relative_path=relative,
            sha256=digest,
            size_bytes=len(data),
            created=True,
        )

    # -------------------------------------------------------------- derived

    def save_derived(
        self,
        data: bytes,
        *,
        run_id: str,
        role: str,
        image_format: str,
    ) -> StoredFile:
        """Persist one pipeline stage output under its run prefix."""
        validate_component(run_id, label="run id")
        validate_component(role, label="artifact role")
        if image_format not in STORAGE_EXTENSIONS:
            raise StorageError(f"unsupported image format: {image_format!r}")
        if not data:
            raise StorageError("refusing to store an empty derived image")

        extension = STORAGE_EXTENSIONS[image_format]
        relative = f"derived/{run_id}/{role}.{extension}"
        try:
            put_blob(
                self._key(relative),
                data,
                access=self.access,
                content_type=MIME_TYPES.get(image_format, "application/octet-stream"),
                allow_overwrite=False,
            )
        except BlobError as exc:
            raise self._error(exc) from exc
        return StoredFile(
            relative_path=relative,
            sha256=sha256_hex(data),
            size_bytes=len(data),
            created=True,
        )

    def delete_derived_run(self, run_id: str) -> None:
        """Remove objects written before a failed run is finalized."""
        validate_component(run_id, label="run id")
        # _key normalizes away a trailing slash; the Blob API requires it.
        prefix = self._key(f"derived/{run_id}") + "/"
        try:
            keys = [
                str(entry.pathname)
                for entry in query_blob_entries(prefix=prefix)
                if isinstance(entry, ListBlob)
            ]
            for start in range(0, len(keys), 1000):
                delete_blob(keys[start : start + 1000])
        except BlobError as exc:
            raise self._error(exc) from exc

    # ---------------------------------------------------------------- reads

    def read(self, relative_path: str) -> bytes:
        try:
            return get_blob(self._key(relative_path), access=self.access).body
        except BlobNotFoundError as exc:
            raise FileNotFoundError("the stored asset file is missing") from exc
        except BlobError as exc:
            raise self._error(exc) from exc

    def iter_read(self, relative_path: str) -> Iterator[bytes]:
        """Stream asset bytes in bounded chunks through the Vercel Blob API."""
        try:
            with stream_blob(self._key(relative_path), access=self.access) as download:
                yield from download
        except BlobNotFoundError as exc:
            raise FileNotFoundError("the stored asset file is missing") from exc
        except BlobError as exc:
            raise self._error(exc) from exc

    def exists(self, relative_path: str) -> bool:
        try:
            head_blob(self._key(relative_path))
            return True
        except BlobNotFoundError:
            return False
        except BlobError as exc:
            raise self._error(exc) from exc

    def describe(self) -> dict[str, object]:
        """Report Blob backend health and real usage for health endpoints."""
        total = 0
        try:
            for entry in query_blob_entries(prefix=self._root_prefix() or None):
                if isinstance(entry, ListBlob):
                    total += int(entry.size)
        except BlobError as exc:
            return {
                "backend": "vercel_blob",
                "available": False,
                "writable": False,
                "free_bytes": 0,
                "bytes_used": 0,
                "error": self._public_error(exc),
            }
        return {
            "backend": "vercel_blob",
            "available": True,
            "writable": True,
            "free_bytes": 0,  # object storage has no meaningful free-byte figure
            "bytes_used": total,
        }

    @staticmethod
    def _public_error(exc: BaseException) -> str:
        return f"Vercel Blob is unavailable ({type(exc).__name__})"
