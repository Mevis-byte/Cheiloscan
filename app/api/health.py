"""Health endpoint: real liveness and dependency reporting."""

from __future__ import annotations

import importlib.metadata

from flask import Blueprint, jsonify
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import get_database
from cheiloscan import __version__

health_bp = Blueprint("health", __name__)


def _dependency_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        return "not-installed"


@health_bp.get("/api/health")
def health():
    database = get_database()
    try:
        schema_version = database.current_schema_version()
        database_state = {"connected": True, "schema_version": schema_version}
        ok = True
    except (SQLAlchemyError, RuntimeError):
        database_state = {"connected": False, "schema_version": None}
        ok = False

    body = {
        "status": "ok" if ok else "error",
        "app": "cheiloscan",
        "version": __version__,
        "database": database_state,
        "dependencies": {
            "flask": _dependency_version("flask"),
            "sqlalchemy": _dependency_version("sqlalchemy"),
        },
    }
    return jsonify(body), (200 if ok else 503)
