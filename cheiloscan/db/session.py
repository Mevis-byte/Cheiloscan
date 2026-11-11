"""Engine and session management for CheiloScan.

``Database`` owns the SQLAlchemy engine, applies SQLite connection pragmas
(WAL journaling, enforced foreign keys, busy timeout) and provides
context-managed sessions that commit on success and roll back on failure.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .migrations import apply_migrations
from .models import SCHEMA_VERSION, Base, SchemaVersion


class Database:
    """Owns the engine and session factory for one database URL."""

    def __init__(self, url: str, echo: bool = False) -> None:
        self.url = url
        self.engine: Engine = create_engine(url, echo=echo, future=True)
        if self.engine.dialect.name == "sqlite":
            _install_sqlite_pragmas(self.engine)
        self._session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, future=True
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a session; commit on success, roll back on any failure."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def init_schema(self) -> int:
        """Create tables if absent, then migrate to ``SCHEMA_VERSION``.

        Idempotent and safe to call on every application startup.

        - fresh database          -> tables created, version stamped;
        - older database          -> ordered migrations applied, then stamped;
        - newer database          -> error (downgrade is never automatic);
        - same version            -> no-op.
        """
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            row = connection.execute(select(SchemaVersion.version)).first()
            if row is None:
                connection.execute(
                    SchemaVersion.__table__.insert().values(version=SCHEMA_VERSION)
                )
                return SCHEMA_VERSION
            found = int(row[0])
            if found > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema version {found} is newer than this "
                    f"application (expects {SCHEMA_VERSION}); refusing to start"
                )
            if found < SCHEMA_VERSION:
                apply_migrations(connection, found, SCHEMA_VERSION)
                connection.execute(
                    SchemaVersion.__table__.update().values(
                        version=SCHEMA_VERSION
                    )
                )
        return SCHEMA_VERSION

    def current_schema_version(self) -> int:
        """Read the stored schema version (raises if the DB is unreachable)."""
        with self.engine.connect() as connection:
            row = connection.execute(select(SchemaVersion.version)).first()
        if row is None:
            raise RuntimeError("schema_version table is empty or missing")
        return int(row[0])

    def dispose(self) -> None:
        self.engine.dispose()


def _install_sqlite_pragmas(engine: Engine) -> None:
    """Apply per-connection SQLite settings required by the design."""

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record) -> None:  # pragma: no cover
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()
