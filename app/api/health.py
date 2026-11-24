"""Health endpoints: liveness, readiness and dependency reporting."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
from pathlib import Path

from flask import Blueprint, current_app, jsonify
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import get_database
from cheiloscan import __version__
from cheiloscan.storage import storage_usage_bytes

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


def _storage_state() -> tuple[dict[str, object], bool]:
    data_dir = Path(current_app.config["DATA_DIR"])
    writable = data_dir.is_dir() and os.access(data_dir, os.W_OK)
    free = shutil.disk_usage(data_dir).free if data_dir.is_dir() else 0
    return {"writable": writable, "free_bytes": free}, writable and free > 0


@health_bp.get("/api/health/live")
def live():
    """Process liveness. Deliberately dependency-free and unauthenticated."""
    return jsonify({"status": "ok", "app": "cheiloscan"})


@health_bp.get("/api/health/ready")
def ready():
    """Readiness: database reachable and data directory writable."""
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
    storage, storage_ok = _storage_state()
    body = {
        "status": "ok" if ok and storage_ok else "error",
        "app": "cheiloscan",
        "version": __version__,
        "database": database,
        "storage": {"bytes_used": storage_usage_bytes(Path(current_app.config["DATA_DIR"]))},
        "dependencies": {
            "flask": _dependency_version("flask"),
            "sqlalchemy": _dependency_version("sqlalchemy"),
        },
    }
    return jsonify(body), (200 if ok and storage_ok else 503)
