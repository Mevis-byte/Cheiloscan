"""Integration tests: application factory and startup behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

from app import create_app
from app.config import load_config_from_env
from cheiloscan.storage import DATA_SUBDIRS
from tests.conftest import make_test_config


def test_create_app_returns_flask_app(app):
    assert isinstance(app, Flask)
    assert app.name == "cheiloscan"


def test_factory_creates_storage_directories(app, test_config):
    data_dir = Path(test_config["DATA_DIR"])
    for name in DATA_SUBDIRS:
        assert (data_dir / name).is_dir(), f"missing storage subdir: {name}"


def test_factory_binds_database_extension(app):
    database = app.extensions["database"]
    assert database.current_schema_version() == 2


def test_factory_rejects_incomplete_config(tmp_path):
    incomplete = make_test_config(tmp_path / "data")
    del incomplete["DATABASE_URL"]
    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_app(incomplete)


def test_create_app_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEILOSCAN_DATA_DIR", str(tmp_path / "envdata"))
    monkeypatch.setenv("CHEILOSCAN_LOG_LEVEL", "DEBUG")
    app = create_app()  # no explicit config: loads from environment
    try:
        assert Path(app.config["DATA_DIR"]) == (tmp_path / "envdata").resolve()
        assert app.config["LOG_LEVEL"] == "DEBUG"
        assert app.extensions["database"].current_schema_version() == 2
    finally:
        app.extensions["database"].dispose()


def test_vercel_profile_uses_blob_store_without_local_dirs(tmp_path, monkeypatch):
    """A Vercel cold start must not create a local data tree."""
    created: dict[str, object] = {}

    class FakeDatabase:
        def __init__(self, url):
            created["database_url"] = url

        def init_schema(self):
            created["schema_initialized"] = True

        def current_schema_version(self):
            return 2

        def dispose(self):
            return None

    class FakeBlobStore:
        def __init__(self, *, prefix, access):
            created["blob_prefix"] = prefix
            created["blob_access"] = access

    monkeypatch.setattr("app.Database", FakeDatabase)
    monkeypatch.setattr("app.VercelBlobAssetStore", FakeBlobStore)
    data_dir = tmp_path / "must-not-be-created"
    config = load_config_from_env(
        env={
            "VERCEL": "1",
            "VERCEL_URL": "cheiloscan.vercel.app",
            "CHEILOSCAN_DATA_DIR": str(data_dir),
            "CHEILOSCAN_DATABASE_URL": "postgres://u:p@h/db",
            "BLOB_READ_WRITE_TOKEN": "vercel_blob_rw_test_secret",
            "CHEILOSCAN_SECRET_KEY": "a-long-random-production-secret-key",
            "CHEILOSCAN_AUTH_USERNAME": "researcher",
            "CHEILOSCAN_AUTH_PASSWORD_HASH": "scrypt:32768:8:1$abc$def",
        }
    )

    application = create_app(config)

    assert not data_dir.exists()
    assert created["database_url"] == "postgresql+psycopg://u:p@h/db"
    assert created["schema_initialized"] is True
    assert created["blob_prefix"] == "cheiloscan"
    assert created["blob_access"] == "private"
    assert isinstance(application.extensions["asset_store"], FakeBlobStore)


def test_ui_pages_are_served(client):
    for path in ("/", "/samples", "/analyses", "/comparisons"):
        response = client.get(path)
        assert response.status_code == 200
        assert b"CheiloScan" in response.data


def test_static_assets_are_served(client):
    assert client.get("/css/style.css").status_code == 200
    assert client.get("/js/app.js").status_code == 200
