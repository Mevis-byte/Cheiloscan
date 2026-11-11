"""Integration tests: database initialization and safety guarantees."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from cheiloscan.db.models import SCHEMA_VERSION
from cheiloscan.db.session import Database


EXPECTED_TABLES = {
    "samples",
    "image_assets",
    "analysis_runs",
    "analysis_artifacts",
    "comparisons",
    "schema_version",
}


def test_init_schema_creates_all_tables(database):
    inspector = inspect(database.engine)
    created = set(inspector.get_table_names())
    assert EXPECTED_TABLES <= created


def test_init_schema_is_idempotent(database):
    # The factory already initialized once; a second run must be safe.
    assert database.init_schema() == SCHEMA_VERSION
    assert database.init_schema() == SCHEMA_VERSION


def test_schema_version_is_stamped(database):
    with database.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT version FROM schema_version")
        ).fetchall()
    assert [row[0] for row in rows] == [SCHEMA_VERSION]


def test_schema_version_table_blocks_silent_downgrade(tmp_path):
    url = "sqlite:///" + (tmp_path / "future.sqlite").as_posix()
    database = Database(url)
    try:
        database.init_schema()
        with database.engine.begin() as connection:
            connection.execute(
                text("UPDATE schema_version SET version = 99")
            )
        with pytest.raises(RuntimeError, match="newer than this application"):
            database.init_schema()
    finally:
        database.dispose()


def test_sqlite_pragmas_are_active(database):
    with database.engine.connect() as connection:
        foreign_keys = connection.execute(
            text("PRAGMA foreign_keys")
        ).scalar()
        journal_mode = connection.execute(
            text("PRAGMA journal_mode")
        ).scalar()
    assert foreign_keys == 1
    assert str(journal_mode).lower() == "wal"


def test_sqlite_busy_timeout_is_set(database):
    with database.engine.connect() as connection:
        timeout = connection.execute(text("PRAGMA busy_timeout")).scalar()
    assert timeout == 5000
