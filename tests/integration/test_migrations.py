"""Integration tests: ordered schema migrations (v1 -> v2)."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import inspect, text

from cheiloscan.db.models import SCHEMA_VERSION
from cheiloscan.db.session import Database

#: The ``analysis_runs`` table exactly as schema v1 created it (no
#: ``results`` column). Kept literal so the test fails if the migration is
#: ever silently skipped.
_V1_ANALYSIS_RUNS = """
CREATE TABLE analysis_runs (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    sample_id VARCHAR(36) NOT NULL,
    input_asset_id VARCHAR(36),
    pipeline_name VARCHAR(120) NOT NULL,
    pipeline_version VARCHAR(40) NOT NULL,
    params JSON NOT NULL,
    status VARCHAR(20) NOT NULL,
    error TEXT,
    started_at DATETIME,
    finished_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY(sample_id) REFERENCES samples (id) ON DELETE RESTRICT,
    FOREIGN KEY(input_asset_id) REFERENCES image_assets (id) ON DELETE RESTRICT
)
"""


def _make_v1_database(path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY, "
            "applied_at DATETIME NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (1, '2026-01-01 00:00:00')"
        )
        connection.execute(_V1_ANALYSIS_RUNS)
        connection.execute(
            "INSERT INTO analysis_runs (id, sample_id, pipeline_name, "
            "pipeline_version, params, status, created_at, updated_at) "
            "VALUES ('run-1', 'sample-1', 'legacy', '1', '{}', 'succeeded', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        connection.commit()
    finally:
        connection.close()


def test_v1_database_is_migrated_to_current_version(tmp_path):
    path = tmp_path / "v1.sqlite"
    _make_v1_database(path)
    database = Database("sqlite:///" + path.as_posix())
    try:
        assert database.init_schema() == SCHEMA_VERSION

        with database.engine.connect() as connection:
            version = connection.execute(
                text("SELECT version FROM schema_version")
            ).scalar()
            columns = [
                row[1]
                for row in connection.execute(text("PRAGMA table_info(analysis_runs)"))
            ]
            legacy = connection.execute(
                text("SELECT id, results FROM analysis_runs WHERE id = 'run-1'")
            ).fetchone()
            tables = set(inspect(connection).get_table_names())

        assert version == SCHEMA_VERSION
        assert "results" in columns
        assert legacy is not None and legacy[0] == "run-1"
        assert legacy[1] is None  # existing rows keep no invented results
        assert "analysis_artifacts" in tables
        assert "samples" in tables and "image_assets" in tables
    finally:
        database.dispose()


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "v1.sqlite"
    _make_v1_database(path)
    database = Database("sqlite:///" + path.as_posix())
    try:
        assert database.init_schema() == SCHEMA_VERSION
        assert database.init_schema() == SCHEMA_VERSION
        with database.engine.connect() as connection:
            columns = [
                row[1]
                for row in connection.execute(text("PRAGMA table_info(analysis_runs)"))
            ]
        assert columns.count("results") == 1
    finally:
        database.dispose()


def test_analysis_artifacts_enforces_one_asset_per_role(tmp_path):
    path = tmp_path / "v1.sqlite"
    _make_v1_database(path)
    database = Database("sqlite:///" + path.as_posix())
    try:
        database.init_schema()
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO samples (id, code, consent_confirmed, created_at, "
                    "updated_at) VALUES ('sample-1', 'S-1', 0, "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO image_assets (id, sample_id, kind, sha256, "
                    "storage_path, format, width, height, size_bytes, created_at, "
                    "updated_at) VALUES ('asset-1', 'sample-1', 'derived', "
                    "'a', 'derived/x/final.png', 'png', 1, 1, 1, "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO analysis_artifacts (id, analysis_run_id, "
                    "image_asset_id, role, created_at, updated_at) VALUES "
                    "('art-1', 'run-1', 'asset-1', 'final', "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )

        with pytest.raises(Exception):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO analysis_artifacts (id, analysis_run_id, "
                        "image_asset_id, role, created_at, updated_at) VALUES "
                        "('art-2', 'run-1', 'asset-1', 'final', "
                        "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                    )
                )
    finally:
        database.dispose()


def test_fresh_database_starts_at_current_version(tmp_path):
    database = Database("sqlite:///" + (tmp_path / "fresh.sqlite").as_posix())
    try:
        assert database.init_schema() == SCHEMA_VERSION
        with database.engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
        assert "analysis_artifacts" in tables
    finally:
        database.dispose()
