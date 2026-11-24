"""Unit tests for the Vercel serverless deployment profile."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from app.config import (
    ConfigurationError,
    load_config_from_env,
    normalize_database_url,
    vercel_hosts,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _vercel_env(**overrides: str) -> dict[str, str]:
    """A complete Vercel environment with required production credentials."""
    env = {
        "VERCEL": "1",
        "VERCEL_ENV": "production",
        "VERCEL_URL": "cheiloscan-git-main-mevis.vercel.app",
        "CHEILOSCAN_DATABASE_URL": "postgresql://user:secret@db.example.com/cheiloscan",
        "BLOB_READ_WRITE_TOKEN": "vercel_blob_rw_test_secret",
        "CHEILOSCAN_SECRET_KEY": "a-long-random-production-secret-key",
        "CHEILOSCAN_AUTH_USERNAME": "researcher",
        "CHEILOSCAN_AUTH_PASSWORD_HASH": "scrypt:32768:8:1$abc$def",
    }
    env.update(overrides)
    return env


def test_vercel_defaults_to_production_postgres_and_blob():
    config = load_config_from_env(env=_vercel_env())
    assert config["DEBUG"] is False
    assert config["BEHIND_PROXY"] is True
    assert config["FORCE_HTTPS"] is True
    assert config["ALLOWED_HOSTS"] == ("cheiloscan-git-main-mevis.vercel.app",)
    assert config["DATABASE_URL"] == (
        "postgresql+psycopg://user:secret@db.example.com/cheiloscan"
    )
    assert config["STORAGE_BACKEND"] == "vercel_blob"
    assert config["BLOB_ACCESS"] == "private"
    assert config["MAX_CONTENT_LENGTH"] == 4 * 1024 * 1024


def test_vercel_prefers_explicit_hosts_and_upload_limit():
    config = load_config_from_env(
        env=_vercel_env(
            CHEILOSCAN_ALLOWED_HOSTS="CheiloScan.example.org, other.example.org",
            CHEILOSCAN_MAX_UPLOAD_MB="20",
            CHEILOSCAN_BLOB_ACCESS="public",
            CHEILOSCAN_STORAGE_PREFIX="research/dev",
        )
    )
    assert config["ALLOWED_HOSTS"] == ("cheiloscan.example.org", "other.example.org")
    assert config["MAX_CONTENT_LENGTH"] == 20 * 1024 * 1024
    assert config["BLOB_ACCESS"] == "public"
    assert config["STORAGE_PREFIX"] == "research/dev"


def test_vercel_rejects_sqlite_and_missing_blob_credentials():
    with pytest.raises(ConfigurationError, match="Postgres"):
        load_config_from_env(
            env=_vercel_env(CHEILOSCAN_DATABASE_URL="sqlite:///data/db/app.sqlite")
        )
    without_token = _vercel_env()
    del without_token["BLOB_READ_WRITE_TOKEN"]
    with pytest.raises(ConfigurationError, match="BLOB_READ_WRITE_TOKEN"):
        load_config_from_env(env=without_token)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///tmp/app.sqlite", "sqlite:///tmp/app.sqlite"),
    ],
)
def test_normalize_database_url(url, expected):
    assert normalize_database_url(url) == expected


def test_vercel_hosts_are_deduplicated_and_stripped():
    assert vercel_hosts(
        {
            "VERCEL_PROJECT_PRODUCTION_URL": "https://cheiloscan.example.org",
            "VERCEL_BRANCH_URL": "cheiloscan-git-main.vercel.app/path",
            "VERCEL_URL": "cheiloscan-git-main.vercel.app",
        }
    ) == ("cheiloscan.example.org", "cheiloscan-git-main.vercel.app")


def test_vercel_manifest_and_static_mirror():
    manifest = json.loads((REPO_ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert manifest["functions"]["wsgi.py"]["maxDuration"] == 300
    assert manifest["functions"]["wsgi.py"]["excludeFiles"]

    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    assert pyproject["tool"]["vercel"]["entrypoint"] == "wsgi:app"
    assert "sync_public.py" in pyproject["tool"]["vercel"]["scripts"]["build"]

    web_files = {
        path.relative_to(REPO_ROOT / "web").as_posix()
        for path in (REPO_ROOT / "web").rglob("*")
        if path.is_file() and path.name != "__init__.py"
    }
    public_files = {
        path.relative_to(REPO_ROOT / "public").as_posix()
        for path in (REPO_ROOT / "public").rglob("*")
        if path.is_file()
    }
    assert web_files == public_files
