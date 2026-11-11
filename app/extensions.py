"""Shared Flask extension access helpers."""

from __future__ import annotations

from flask import current_app

from cheiloscan.db.session import Database


def get_database() -> Database:
    """Return the database extension bound to the current application."""
    try:
        database: Database = current_app.extensions["database"]
    except KeyError as exc:
        raise RuntimeError(
            "database extension is not initialized; was create_app used?"
        ) from exc
    return database
