"""Ordered schema migrations.

The application schema is versioned by the single-row ``schema_version``
table. ``Database.init_schema`` creates any missing tables and then applies
every migration between the stored version and ``SCHEMA_VERSION`` in order.

Migration rules (portable across SQLite and Postgres, see
docs/ARCHITECTURE.md §6):

- New tables are created with ``create_all`` semantics, so they need no
  explicit migration for a fresh database. An existing database gets them
  because ``init_schema`` calls ``create_all`` before migrating.
- New *columns* on existing tables need ``ALTER TABLE ... ADD COLUMN``
  (SQLite has no ``ADD CONSTRAINT``; keep column additions nullable or
  defaulted so they are valid for existing rows).
- Every migration must be idempotent: it is safe to re-run after a crash
  between the DDL and the version stamp.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from .models import SCHEMA_VERSION, AnalysisArtifact

#: A migration transforms a connection from version ``key`` to ``key + 1``.
Migration = Callable[[Connection], None]


def _table_exists(connection: Connection, table: str) -> bool:
    return table in inspect(connection).get_table_names()


def _column_exists(connection: Connection, table: str, column_name: str) -> bool:
    """Portable column check (SQLAlchemy inspector works on SQLite and Postgres)."""
    if not _table_exists(connection, table):
        return False
    return any(
        column["name"] == column_name
        for column in inspect(connection).get_columns(table)
    )


def _v1_to_v2(connection: Connection) -> None:
    """Schema v2: analysis outputs + derived-artifact association table.

    Adds ``analysis_runs.results`` (measured outputs, kept apart from the
    ``params`` input snapshot) and creates ``analysis_artifacts``, which
    replaces the mutually-referencing ``ImageAsset.analysis_run_id`` link
    planned in Phase 1.
    """
    if not _column_exists(connection, "analysis_runs", "results"):
        connection.execute(
            text("ALTER TABLE analysis_runs ADD COLUMN results JSON")
        )
    AnalysisArtifact.__table__.create(bind=connection, checkfirst=True)


#: ``MIGRATIONS[n]`` upgrades a database from version ``n`` to ``n + 1``.
MIGRATIONS: dict[int, Migration] = {
    1: _v1_to_v2,
}


def apply_migrations(
    connection: Connection, from_version: int, to_version: int = SCHEMA_VERSION
) -> int:
    """Apply every pending migration in order and return the new version.

    Raises ``RuntimeError`` if a required step has no implementation, which
    indicates a version bump without a migration (a programming error).
    """
    if to_version < from_version:
        raise RuntimeError(
            f"cannot migrate downwards from {from_version} to {to_version}"
        )
    version = from_version
    while version < to_version:
        step = MIGRATIONS.get(version)
        if step is None:
            raise RuntimeError(
                f"no migration registered from schema version {version} to "
                f"{version + 1}"
            )
        step(connection)
        version += 1
    return version
