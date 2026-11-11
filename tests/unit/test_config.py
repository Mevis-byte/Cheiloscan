"""Unit tests for environment-driven configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import (
    ConfigurationError,
    default_database_url,
    load_config_from_env,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_defaults_are_valid():
    config = load_config_from_env(env={})
    assert config["DEBUG"] is True  # development is the default environment
    assert config["TESTING"] is False
    assert config["LOG_LEVEL"] == "INFO"
    assert config["LOG_FORMAT"] == "json"
    assert config["MAX_CONTENT_LENGTH"] == 25 * 1024 * 1024
    # An ephemeral development secret is generated when none is provided.
    assert isinstance(config["SECRET_KEY"], str) and config["SECRET_KEY"]


def test_data_dir_is_resolved_absolute(tmp_path):
    config = load_config_from_env(env={"CHEILOSCAN_DATA_DIR": str(tmp_path)})
    assert Path(config["DATA_DIR"]).is_absolute()
    assert Path(config["DATA_DIR"]) == tmp_path.resolve()


def test_database_url_defaults_under_data_dir(tmp_path):
    config = load_config_from_env(env={"CHEILOSCAN_DATA_DIR": str(tmp_path)})
    expected = default_database_url(tmp_path.resolve())
    assert config["DATABASE_URL"] == expected
    assert expected.startswith("sqlite:///")


def test_database_url_override_wins(tmp_path):
    url = "sqlite:///" + (tmp_path / "custom.sqlite").as_posix()
    config = load_config_from_env(
        env={"CHEILOSCAN_DATA_DIR": str(tmp_path), "CHEILOSCAN_DATABASE_URL": url}
    )
    assert config["DATABASE_URL"] == url


def test_upload_size_from_mb():
    config = load_config_from_env(env={"CHEILOSCAN_MAX_UPLOAD_MB": "12"})
    assert config["MAX_CONTENT_LENGTH"] == 12 * 1024 * 1024


@pytest.mark.parametrize(
    "overrides",
    [
        {"CHEILOSCAN_ENV": "production"},  # missing secret key
        {"CHEILOSCAN_ENV": "staging"},
        {"CHEILOSCAN_LOG_LEVEL": "LOUD"},
        {"CHEILOSCAN_LOG_FORMAT": "xml"},
        {"CHEILOSCAN_MAX_UPLOAD_MB": "zero"},
        {"CHEILOSCAN_MAX_UPLOAD_MB": "0"},
    ],
)
def test_invalid_configuration_fails_fast(overrides):
    with pytest.raises(ConfigurationError):
        load_config_from_env(env=overrides)


def test_production_requires_secret_key():
    config = load_config_from_env(
        env={
            "CHEILOSCAN_ENV": "production",
            "CHEILOSCAN_SECRET_KEY": "a-real-secret",
        }
    )
    assert config["SECRET_KEY"] == "a-real-secret"
    assert config["DEBUG"] is False


def test_env_example_exists_and_documents_variables():
    example = REPO_ROOT / ".env.example"
    assert example.is_file()
    content = example.read_text(encoding="utf-8")
    for variable in (
        "CHEILOSCAN_DATA_DIR",
        "CHEILOSCAN_DATABASE_URL",
        "CHEILOSCAN_MAX_UPLOAD_MB",
        "CHEILOSCAN_LOG_LEVEL",
        "CHEILOSCAN_LOG_FORMAT",
        "CHEILOSCAN_SECRET_KEY",
    ):
        assert variable in content
