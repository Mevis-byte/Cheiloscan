"""Content-addressed local asset store.

Layout (docs/ARCHITECTURE.md §6.1)::

    <data_dir>/original/<aa>/<sha256>.<ext>     immutable uploads
    <data_dir>/derived/<run_id>/<role>.<ext>    pipeline outputs

Guarantees:

- **Originals are never overwritten.** The filename *is* the SHA-256 of the
  bytes, so the same bytes always map to the same path. An existing file is
  re-hashed before being accepted; a mismatch raises instead of replacing it.
  New originals are written atomically (temp file + ``os.replace``) and set
  read-only on a best-effort basis.
- **Derived files are per-run**, so re-running a pipeline can never clobber
  another run's outputs.
- **Containment.** Every path handed out is resolved and verified to live
  under the configured data directory; caller-supplied path components are
  validated against a strict character set.

This is the default backend for local development and single-process
deployments. Vercel deployments use :class:`VercelBlobAssetStore` instead,
behind the same :class:`~cheiloscan.storage.base.AssetStoreLike` contract.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterator

from . import storage_usage_bytes
from .base import (
    AssetStoreLike,
    StorageError,
    StoredFile,
    validate_component,
    validate_relative_path,
)
from ..util.imageio import STORAGE_EXTENSIONS, sha256_hex

__all__ = ["AssetStore", "StorageError", "StoredFile"]


class AssetStore(AssetStoreLike):
    """Filesystem store for original and derived image assets."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.original_root = self.data_dir / "original"
        self.derived_root = self.data_dir / "derived"
        self.original_root.mkdir(parents=True, exist_ok=True)
        self.derived_root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- paths

    def resolve(self, relative_path: str) -> Path:
        """Resolve a store-relative path, refusing anything outside the store."""
        validated = validate_relative_path(relative_path)
        candidate = Path(validated)
        resolved = (self.data_dir / candidate).resolve()
        if resolved != self.data_dir and self.data_dir not in resolved.parents:
            raise StorageError(
                f"storage path escapes the data directory: {relative_path!r}"
            )
        return resolved

    # ------------------------------------------------------------ originals

    def save_original(self, data: bytes, image_format: str) -> StoredFile:
        """Persist immutable original bytes, deduplicating by content hash."""
        if image_format not in STORAGE_EXTENSIONS:
            raise StorageError(f"unsupported image format: {image_format!r}")
        if not data:
            raise StorageError("refusing to store an empty original")

        digest = sha256_hex(data)
        extension = STORAGE_EXTENSIONS[image_format]
        relative = Path("original") / digest[:2] / f"{digest}.{extension}"
        target = self.resolve(relative.as_posix())

        if target.exists():
            existing = target.read_bytes()
            if sha256_hex(existing) != digest:
                raise StorageError(
                    "stored original does not match its content address; "
                    "refusing to overwrite"
                )
            return StoredFile(
                relative_path=relative.as_posix(),
                sha256=digest,
                size_bytes=len(existing),
                created=False,
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(target, data)
        _make_read_only(target)
        return StoredFile(
            relative_path=relative.as_posix(),
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
        """Persist one pipeline stage output under its run directory."""
        validate_component(run_id, label="run id")
        validate_component(role, label="artifact role")
        if image_format not in STORAGE_EXTENSIONS:
            raise StorageError(f"unsupported image format: {image_format!r}")
        if not data:
            raise StorageError("refusing to store an empty derived image")

        extension = STORAGE_EXTENSIONS[image_format]
        relative = Path("derived") / run_id / f"{role}.{extension}"
        target = self.resolve(relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(target, data)
        return StoredFile(
            relative_path=relative.as_posix(),
            sha256=sha256_hex(data),
            size_bytes=len(data),
            created=True,
        )

    def delete_derived_run(self, run_id: str) -> None:
        """Remove stage files written before a failed run is finalized."""
        validate_component(run_id, label="run id")
        directory = self.resolve(f"derived/{run_id}")
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)

    # ---------------------------------------------------------------- reads

    def read(self, relative_path: str) -> bytes:
        return self.resolve(relative_path).read_bytes()

    def iter_read(self, relative_path: str) -> Iterator[bytes]:
        """Stream asset bytes in bounded chunks (avoids buffering in memory)."""
        with self.resolve(relative_path).open("rb") as handle:
            while True:
                chunk = handle.read(64 * 1024)
                if not chunk:
                    return
                yield chunk

    def exists(self, relative_path: str) -> bool:
        return self.resolve(relative_path).is_file()

    def describe(self) -> dict[str, object]:
        """Report local backend health and real usage for health endpoints."""
        try:
            free_bytes = shutil.disk_usage(self.data_dir).free
        except OSError:  # pragma: no cover - unusual mounted filesystems
            free_bytes = 0
        writable = self.data_dir.is_dir() and os.access(self.data_dir, os.W_OK)
        available = writable and free_bytes > 0
        return {
            "backend": "local",
            "available": available,
            "writable": writable,
            "free_bytes": free_bytes,
            "bytes_used": storage_usage_bytes(self.data_dir),
        }

    # ------------------------------------------------------------- internal

    @staticmethod
    def _atomic_write(target: Path, data: bytes) -> None:
        descriptor, temp_name = tempfile.mkstemp(
            dir=target.parent, prefix=".tmp-", suffix=target.suffix
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:  # pragma: no cover - temp file already gone
                pass
            raise


def _make_read_only(path: Path) -> None:
    """Best-effort write protection for immutable originals."""
    try:
        path.chmod(0o444)
    except OSError:  # pragma: no cover - e.g. DrvFs mounts without chmod
        pass
