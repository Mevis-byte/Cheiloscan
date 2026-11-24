"""Health endpoints: liveness, readiness and dependency reporting."""

from __future__ import annotations

import importlib.metadata

from flask import Blueprint, jsonify
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import get_asset_store, get_database
from cheiloscan import __version__

health_bp = Blueprint("health", __name__)


def _dependency_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        return "not-installed"


def _database_state() -> tuple[dict[str, object], bool]:
    database = get_database()
    try:
        schema_version = database.current_schema_version()
        return {"connected": True, "schema_version": schema_version}, True
    except (SQLAlchemyError, RuntimeError):
        return {"connected": False, "schema_version": None}, False


def _storage_report() -> tuple[dict[str, object], bool]:
    """Ask the configured store about its own health (local disk or Blob)."""
    try:
        info = get_asset_store().describe()
    except Exception:  # noqa: BLE001 - health must report, never leak details
        info = {"backend": "unknown", "available": False}
    available = bool(info.get("available"))
    report: dict[str, object] = {
        "backend": str(info.get("backend", "unknown")),
        "available": available,
        "writable": bool(info.get("writable", available)),
        "free_bytes": int(info.get("free_bytes", 0) or 0),
        "bytes_used": int(info.get("bytes_used", 0) or 0),
    }
    return report, available


def _storage_state() -> tuple[dict[str, object], bool]:
    report, available = _storage_report()
    return {
        "backend": report["backend"],
        "available": report["available"],
        "writable": report["writable"],
        "free_bytes": report["free_bytes"],
    }, available


@health_bp.get("/api/health/live")
def live():
    """Process liveness. Deliberately dependency-free and unauthenticated."""
    return jsonify({"status": "ok", "app": "cheiloscan"})


@health_bp.get("/api/health/ready")
def ready():
    """Readiness: database reachable and durable storage available."""
    database, database_ok = _database_state()
    storage, storage_ok = _storage_state()
    ok = database_ok and storage_ok
    return (
        jsonify(
            {
                "status": "ok" if ok else "error",
                "database": database,
                "storage": storage,
            }
        ),
        200 if ok else 503,
    )


@health_bp.get("/api/health")
def health():
    """Detailed health report (authenticated in production)."""
    database, ok = _database_state()
    storage, storage_ok = _storage_report()
    body = {
        "status": "ok" if ok and storage_ok else "error",
        "app": "cheiloscan",
        "version": __version__,
        "database": database,
        "storage": {
            "backend": storage["backend"],
            "bytes_used": storage["bytes_used"],
        },
        "dependencies": {
            "flask": _dependency_version("flask"),
            "sqlalchemy": _dependency_version("sqlalchemy"),
        },
    }
    return jsonify(body), (200 if ok and storage_ok else 503)
