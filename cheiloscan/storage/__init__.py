"""Storage layout helpers shared by local and serverless backends.

The local directory tree is documented in docs/ARCHITECTURE.md §6.1. On
Vercel these helpers are not used for durable data; the asset store is backed
by Vercel Blob behind the same contract.
"""

from __future__ import annotations

from pathlib import Path

DATA_SUBDIRS = ("db", "original", "derived", "reports")


def ensure_storage_directories(data_dir: Path) -> dict[str, Path]:
    """Create the data directory tree if absent and return the subdirectories.

    Idempotent and safe to call on every application startup.
    """
    data_dir = Path(data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    resolved: dict[str, Path] = {"root": data_dir}
    for name in DATA_SUBDIRS:
        sub = data_dir / name
        sub.mkdir(parents=True, exist_ok=True)
        resolved[name] = sub
    return resolved


def storage_usage_bytes(data_dir: Path) -> int:
    """Total size in bytes of all files under ``data_dir`` (real usage)."""
    data_dir = Path(data_dir)
    if not data_dir.exists():
        return 0
    total = 0
    for entry in data_dir.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:  # pragma: no cover - file vanished mid-walk
                continue
    return total
