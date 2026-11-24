"""Shared pytest fixtures.

Every test gets its own throwaway data directory and SQLite database file
(function-scoped); the repository's real ``data/`` directory is never
touched by tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app
from app.config import (
    DEFAULT_MAX_IMAGE_DIMENSION,
    DEFAULT_MIN_IMAGE_DIMENSION,
    DEFAULT_QUALITY_MAX_BRIGHTNESS,
    DEFAULT_QUALITY_MAX_CLIPPED_FRACTION,
    DEFAULT_QUALITY_MIN_BLUR_VARIANCE,
    DEFAULT_QUALITY_MIN_BRIGHTNESS,
    DEFAULT_QUALITY_MIN_CONTRAST,
    DEFAULT_QUALITY_RECOMMENDED_MIN_DIMENSION,
    default_database_url,
)


def make_test_config(data_dir: Path) -> dict[str, object]:
    """A complete, isolated configuration for one test."""
    return {
        "SECRET_KEY": "test-secret-key",
        "DEBUG": False,
        "TESTING": True,
        # Exercise the centralized error handlers, not Flask's re-raise.
        "PROPAGATE_EXCEPTIONS": False,
        "DATA_DIR": str(data_dir),
        "DATABASE_URL": default_database_url(data_dir),
        "STORAGE_BACKEND": "local",
        "STORAGE_PREFIX": "cheiloscan",
        "BLOB_ACCESS": "private",
        "MAX_CONTENT_LENGTH": 1024 * 1024,
        "LOG_LEVEL": "WARNING",
        "LOG_FORMAT": "json",
        "HOST": "127.0.0.1",
        "PORT": 5000,
        "THREADS": 2,
        "AUTH_ENABLED": False,
        "AUTH_USERNAME": "",
        "AUTH_PASSWORD_HASH": "",
        "AUTH_MAX_FAILURES": 10,
        "AUTH_LOCKOUT_SECONDS": 60,
        "BEHIND_PROXY": False,
        "TRUSTED_PROXY_COUNT": 1,
        "FORCE_HTTPS": False,
        "ALLOWED_HOSTS": (),
        "MIN_IMAGE_DIMENSION": DEFAULT_MIN_IMAGE_DIMENSION,
        "MAX_IMAGE_DIMENSION": DEFAULT_MAX_IMAGE_DIMENSION,
        "MAX_IMAGE_PIXELS": 20_000_000,
        "QUALITY_RECOMMENDED_MIN_DIMENSION": DEFAULT_QUALITY_RECOMMENDED_MIN_DIMENSION,
        "QUALITY_MIN_BLUR_VARIANCE": DEFAULT_QUALITY_MIN_BLUR_VARIANCE,
        "QUALITY_MIN_BRIGHTNESS": DEFAULT_QUALITY_MIN_BRIGHTNESS,
        "QUALITY_MAX_BRIGHTNESS": DEFAULT_QUALITY_MAX_BRIGHTNESS,
        "QUALITY_MIN_CONTRAST": DEFAULT_QUALITY_MIN_CONTRAST,
        "QUALITY_MAX_CLIPPED_FRACTION": DEFAULT_QUALITY_MAX_CLIPPED_FRACTION,
    }


@pytest.fixture
def test_config(tmp_path: Path) -> dict[str, object]:
    return make_test_config(tmp_path / "data")


@pytest.fixture
def app(test_config):
    application = create_app(test_config)
    yield application
    application.extensions["database"].dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def database(app):
    return app.extensions["database"]
