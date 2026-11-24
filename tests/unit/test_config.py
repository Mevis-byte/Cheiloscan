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


def test_production_requires_secret_key_and_auth():
    config = load_config_from_env(
        env={
            "CHEILOSCAN_ENV": "production",
            "CHEILOSCAN_SECRET_KEY": "a-long-random-production-secret-key",
            "CHEILOSCAN_AUTH_USERNAME": "researcher",
            "CHEILOSCAN_AUTH_PASSWORD_HASH": "scrypt:32768:8:1$abc$def",
            "CHEILOSCAN_BEHIND_PROXY": "1",
            "CHEILOSCAN_FORCE_HTTPS": "1",
            "CHEILOSCAN_ALLOWED_HOSTS": "research.example.org",
        }
    )
    assert config["SECRET_KEY"] == "a-long-random-production-secret-key"
    assert config["DEBUG"] is False
    assert config["AUTH_ENABLED"] is True
    assert config["THREADS"] == 2
    assert config["BEHIND_PROXY"] is True
    assert config["FORCE_HTTPS"] is True


def test_production_requires_tls_termination():
    base = {
        "CHEILOSCAN_ENV": "production",
        "CHEILOSCAN_SECRET_KEY": "a-long-random-production-secret-key",
        "CHEILOSCAN_AUTH_USERNAME": "researcher",
        "CHEILOSCAN_AUTH_PASSWORD_HASH": "scrypt:32768:8:1$abc$def",
    }
    with pytest.raises(ConfigurationError, match="TLS"):
        load_config_from_env(env=base)
    config = load_config_from_env(
        env={
            **base,
            "CHEILOSCAN_BEHIND_PROXY": "1",
            "CHEILOSCAN_FORCE_HTTPS": "1",
            "CHEILOSCAN_ALLOWED_HOSTS": "research.example.org",
        }
    )
    assert config["ALLOWED_HOSTS"] == ("research.example.org",)
    assert config["FORCE_HTTPS"] is True


def test_development_refuses_non_loopback_debug_bind():
    with pytest.raises(ConfigurationError, match="loopback"):
        load_config_from_env(env={"CHEILOSCAN_HOST": "0.0.0.0"})


def test_short_secret_is_rejected():
    with pytest.raises(ConfigurationError, match="at least 32"):
        load_config_from_env(env={"CHEILOSCAN_SECRET_KEY": "short"})


def test_pixel_budget_is_configurable():
    config = load_config_from_env(env={"CHEILOSCAN_MAX_IMAGE_PIXELS": "5000000"})
    assert config["MAX_IMAGE_PIXELS"] == 5_000_000


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
        "CHEILOSCAN_AUTH_USERNAME",
        "CHEILOSCAN_AUTH_PASSWORD_HASH",
        "CHEILOSCAN_AUTH_MAX_FAILURES",
        "CHEILOSCAN_AUTH_LOCKOUT_SECONDS",
        "CHEILOSCAN_BEHIND_PROXY",
        "CHEILOSCAN_TRUSTED_PROXY_COUNT",
        "CHEILOSCAN_FORCE_HTTPS",
        "CHEILOSCAN_ALLOWED_HOSTS",
        "CHEILOSCAN_HOST",
        "CHEILOSCAN_PORT",
        "CHEILOSCAN_THREADS",
        "CHEILOSCAN_MAX_IMAGE_PIXELS",
    ):
        assert variable in content
