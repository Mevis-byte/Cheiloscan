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
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..util.imageio import STORAGE_EXTENSIONS, sha256_hex

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class StorageError(RuntimeError):
    """A storage operation would violate an integrity guarantee."""


@dataclass(frozen=True)
class StoredFile:
    """A file written to (or found in) the store."""

    relative_path: str
    sha256: str
    size_bytes: int
    created: bool


def _validate_component(name: str, *, label: str) -> str:
    if not _SAFE_COMPONENT.match(name) or name in {".", ".."}:
        raise StorageError(f"invalid {label}: {name!r}")
    return name


class AssetStore:
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
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise StorageError(f"unsafe storage path: {relative_path!r}")
        resolved = (self.data_dir / candidate).resolve()
        if resolved != self.data_dir and self.data_dir not in resolved.parents:
            raise StorageError(f"storage path escapes the data directory: {relative_path!r}")
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
        _validate_component(run_id, label="run id")
        _validate_component(role, label="artifact role")
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

    # ---------------------------------------------------------------- reads

    def read(self, relative_path: str) -> bytes:
        return self.resolve(relative_path).read_bytes()

    def exists(self, relative_path: str) -> bool:
        return self.resolve(relative_path).is_file()

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
