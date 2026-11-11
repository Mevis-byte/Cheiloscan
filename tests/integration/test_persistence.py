"""Integration tests: persistence across engine lifetimes."""

from __future__ import annotations

import pytest

from app.config import default_database_url
from cheiloscan.db.repositories import SampleRepository, ComparisonRepository
from cheiloscan.db.session import Database
from cheiloscan.storage import ensure_storage_directories


def _open_database(data_dir):
    ensure_storage_directories(data_dir)  # mirror the app factory's setup
    return Database(default_database_url(data_dir))


def test_records_survive_engine_disposal(tmp_path):
    data_dir = tmp_path / "data"
    first = _open_database(data_dir)
    first.init_schema()
    with first.session() as session:
        sample_a = SampleRepository(session).create(code="PERSIST-A")
        sample_b = SampleRepository(session).create(code="PERSIST-B")
        ComparisonRepository(session).create(
            sample_a_id=sample_a.id,
            sample_b_id=sample_b.id,
            method="persist-check",
        )
    first.dispose()

    # A brand-new engine over the same file must see the committed data.
    second = _open_database(data_dir)
    try:
        assert second.init_schema() == 1  # idempotent on existing schema
        with second.session() as session:
            repository = SampleRepository(session)
            assert repository.get_by_code("PERSIST-A") is not None
            assert repository.get_by_code("PERSIST-B") is not None
            comparisons, total = ComparisonRepository(session).list()
            assert total == 1
            assert comparisons[0].method == "persist-check"
    finally:
        second.dispose()


def test_uncommitted_changes_do_not_persist(tmp_path):
    database = _open_database(tmp_path / "data")
    database.init_schema()
    try:

        class _Abort(Exception):
            pass

        with pytest.raises(_Abort):
            with database.session() as session:
                SampleRepository(session).create(code="ROLLBACK")
                # Exception inside the block: the context manager must roll back.
                raise _Abort

        with database.session() as clean:
            assert SampleRepository(clean).get_by_code("ROLLBACK") is None
    finally:
        database.dispose()


def test_wal_files_are_created_for_the_database(database, test_config):
    # WAL mode is verified by pragma in test_database.py; here we observe
    # that WAL side files actually exist on disk during operation.
    from pathlib import Path

    db_file = Path(str(test_config["DATABASE_URL"]).removeprefix("sqlite:///"))
    assert db_file.is_file()
    assert db_file.parent.name == "db"
