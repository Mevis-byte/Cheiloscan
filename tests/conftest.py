"""Shared pytest fixtures.

Every test gets its own throwaway data directory and SQLite database file
(function-scoped); the repository's real ``data/`` directory is never
touched by tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app
from app.config import default_database_url


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
        "MAX_CONTENT_LENGTH": 1024 * 1024,
        "LOG_LEVEL": "WARNING",
        "LOG_FORMAT": "json",
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
