"""Shared Flask extension access helpers."""

from __future__ import annotations

from flask import current_app

from cheiloscan.db.session import Database
from cheiloscan.storage.base import AssetStoreLike


def get_database() -> Database:
    """Return the database extension bound to the current application."""
    try:
        database: Database = current_app.extensions["database"]
    except KeyError as exc:
        raise RuntimeError(
            "database extension is not initialized; was create_app used?"
        ) from exc
    return database


def get_asset_store() -> AssetStoreLike:
    """Return the asset store extension bound to the current application."""
    try:
        store: AssetStoreLike = current_app.extensions["asset_store"]
    except KeyError as exc:
        raise RuntimeError(
            "asset store extension is not initialized; was create_app used?"
        ) from exc
    return store
