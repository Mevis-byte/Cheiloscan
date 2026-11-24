"""Shared contracts and path validation for asset store implementations.

Both the local filesystem store and the Vercel Blob store address assets by a
store-relative POSIX path. Validating that path in one place keeps the
containment guarantee identical across backends.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterator, Protocol, runtime_checkable

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


def validate_component(name: str, *, label: str) -> str:
    """Accept only safe single path components (run ids, roles, prefixes)."""
    if not _SAFE_COMPONENT.match(name) or name in {".", ".."}:
        raise StorageError(f"invalid {label}: {name!r}")
    return name


def validate_relative_path(relative_path: str) -> str:
    """Validate a store-relative POSIX path and return it normalized."""
    if not relative_path or "\\" in relative_path:
        raise StorageError(f"unsafe storage path: {relative_path!r}")
    candidate = PurePosixPath(relative_path)
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise StorageError(f"unsafe storage path: {relative_path!r}")
    for part in candidate.parts:
        validate_component(part, label="storage path")
    return candidate.as_posix()


@runtime_checkable
class AssetStoreLike(Protocol):
    """Operations the application requires from an asset store."""

    def save_original(self, data: bytes, image_format: str) -> StoredFile: ...

    def save_derived(
        self,
        data: bytes,
        *,
        run_id: str,
        role: str,
        image_format: str,
    ) -> StoredFile: ...

    def read(self, relative_path: str) -> bytes: ...

    def iter_read(self, relative_path: str) -> Iterator[bytes]: ...

    def exists(self, relative_path: str) -> bool: ...

    def delete_derived_run(self, run_id: str) -> None: ...

    def describe(self) -> dict[str, object]: ...
