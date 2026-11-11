"""Application configuration.

Environment-driven configuration with fail-fast validation. The canonical
variable names are documented in ``.env.example``. Values are read from the
process environment (``run.py`` loads ``.env`` via python-dotenv before the
application factory is called).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

ENV_PREFIX = "CHEILOSCAN_"

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
VALID_LOG_FORMATS = {"json", "plain"}
VALID_ENVIRONMENTS = {"development", "production"}

DEFAULT_DATA_DIR = "data"
DEFAULT_MAX_UPLOAD_MB = 25

#: Absolute dimension limits (hard rejection outside this range).
DEFAULT_MIN_IMAGE_DIMENSION = 128
DEFAULT_MAX_IMAGE_DIMENSION = 12000

#: Experimental quality thresholds (warnings only, never auto-rejection).
DEFAULT_QUALITY_RECOMMENDED_MIN_DIMENSION = 400
DEFAULT_QUALITY_MIN_BLUR_VARIANCE = 60.0
DEFAULT_QUALITY_MIN_BRIGHTNESS = 40.0
DEFAULT_QUALITY_MAX_BRIGHTNESS = 215.0
DEFAULT_QUALITY_MIN_CONTRAST = 25.0
DEFAULT_QUALITY_MAX_CLIPPED_FRACTION = 0.02

# Configuration keys used by the application factory.
CONFIG_KEYS = (
    "SECRET_KEY",
    "DEBUG",
    "TESTING",
    "PROPAGATE_EXCEPTIONS",
    "DATA_DIR",
    "DATABASE_URL",
    "MAX_CONTENT_LENGTH",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "MIN_IMAGE_DIMENSION",
    "MAX_IMAGE_DIMENSION",
    "QUALITY_RECOMMENDED_MIN_DIMENSION",
    "QUALITY_MIN_BLUR_VARIANCE",
    "QUALITY_MIN_BRIGHTNESS",
    "QUALITY_MAX_BRIGHTNESS",
    "QUALITY_MIN_CONTRAST",
    "QUALITY_MAX_CLIPPED_FRACTION",
)


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


def _get(env: Mapping[str, str], name: str, default: str | None = None) -> str:
    value = env.get(name)
    if value is None or value == "":
        return default if default is not None else ""
    return value


def _get_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _get(env, name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from exc


def _get_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _get(env, name, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}") from exc


def default_database_url(data_dir: Path) -> str:
    """SQLite URL for ``<data_dir>/db/app.sqlite`` (absolute, POSIX form)."""
    return "sqlite:///" + (data_dir / "db" / "app.sqlite").as_posix()


def load_config_from_env(
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Build the application configuration mapping from the environment."""
    if env is None:
        env = os.environ

    environment = _get(env, ENV_PREFIX + "ENV", "development").lower()
    if environment not in VALID_ENVIRONMENTS:
        raise ConfigurationError(
            f"CHEILOSCAN_ENV must be one of {sorted(VALID_ENVIRONMENTS)}, "
            f"got {environment!r}"
        )

    log_level = _get(env, ENV_PREFIX + "LOG_LEVEL", "INFO").upper()
    if log_level not in VALID_LOG_LEVELS:
        raise ConfigurationError(
            f"CHEILOSCAN_LOG_LEVEL must be one of {sorted(VALID_LOG_LEVELS)}, "
            f"got {log_level!r}"
        )

    log_format = _get(env, ENV_PREFIX + "LOG_FORMAT", "json").lower()
    if log_format not in VALID_LOG_FORMATS:
        raise ConfigurationError(
            f"CHEILOSCAN_LOG_FORMAT must be one of {sorted(VALID_LOG_FORMATS)}, "
            f"got {log_format!r}"
        )

    max_upload_mb = _get_int(env, ENV_PREFIX + "MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB)
    if max_upload_mb <= 0:
        raise ConfigurationError(
            f"CHEILOSCAN_MAX_UPLOAD_MB must be positive, got {max_upload_mb}"
        )

    min_dimension = _get_int(
        env, ENV_PREFIX + "MIN_IMAGE_DIMENSION", DEFAULT_MIN_IMAGE_DIMENSION
    )
    max_dimension = _get_int(
        env, ENV_PREFIX + "MAX_IMAGE_DIMENSION", DEFAULT_MAX_IMAGE_DIMENSION
    )
    if min_dimension <= 0:
        raise ConfigurationError(
            f"CHEILOSCAN_MIN_IMAGE_DIMENSION must be positive, got {min_dimension}"
        )
    if max_dimension <= min_dimension:
        raise ConfigurationError(
            "CHEILOSCAN_MAX_IMAGE_DIMENSION must be greater than "
            f"CHEILOSCAN_MIN_IMAGE_DIMENSION (got {max_dimension} <= {min_dimension})"
        )

    recommended = _get_int(
        env,
        ENV_PREFIX + "QUALITY_RECOMMENDED_MIN_DIMENSION",
        DEFAULT_QUALITY_RECOMMENDED_MIN_DIMENSION,
    )
    min_blur = _get_float(
        env, ENV_PREFIX + "QUALITY_MIN_BLUR_VARIANCE", DEFAULT_QUALITY_MIN_BLUR_VARIANCE
    )
    min_brightness = _get_float(
        env, ENV_PREFIX + "QUALITY_MIN_BRIGHTNESS", DEFAULT_QUALITY_MIN_BRIGHTNESS
    )
    max_brightness = _get_float(
        env, ENV_PREFIX + "QUALITY_MAX_BRIGHTNESS", DEFAULT_QUALITY_MAX_BRIGHTNESS
    )
    min_contrast = _get_float(
        env, ENV_PREFIX + "QUALITY_MIN_CONTRAST", DEFAULT_QUALITY_MIN_CONTRAST
    )
    max_clipped = _get_float(
        env,
        ENV_PREFIX + "QUALITY_MAX_CLIPPED_FRACTION",
        DEFAULT_QUALITY_MAX_CLIPPED_FRACTION,
    )
    if min_blur < 0:
        raise ConfigurationError("CHEILOSCAN_QUALITY_MIN_BLUR_VARIANCE must be >= 0")
    if min_brightness >= max_brightness:
        raise ConfigurationError(
            "CHEILOSCAN_QUALITY_MIN_BRIGHTNESS must be below "
            "CHEILOSCAN_QUALITY_MAX_BRIGHTNESS"
        )
    if min_contrast < 0:
        raise ConfigurationError("CHEILOSCAN_QUALITY_MIN_CONTRAST must be >= 0")
    if not 0.0 <= max_clipped <= 1.0:
        raise ConfigurationError(
            "CHEILOSCAN_QUALITY_MAX_CLIPPED_FRACTION must be between 0 and 1"
        )

    data_dir = Path(
        _get(env, ENV_PREFIX + "DATA_DIR", DEFAULT_DATA_DIR)
    ).expanduser().resolve()

    database_url = _get(env, ENV_PREFIX + "DATABASE_URL") or default_database_url(
        data_dir
    )

    secret_key = _get(env, ENV_PREFIX + "SECRET_KEY")
    if environment == "production" and not secret_key:
        raise ConfigurationError(
            "CHEILOSCAN_SECRET_KEY must be set when CHEILOSCAN_ENV=production"
        )
    if not secret_key:
        # Development fallback: ephemeral per-process key. Only acceptable
        # because no sessions or cookies with security guarantees exist yet.
        secret_key = os.urandom(32).hex()

    return {
        "SECRET_KEY": secret_key,
        "DEBUG": environment == "development",
        "TESTING": False,
        # Keep Flask from swallowing exceptions past our centralized handlers.
        "PROPAGATE_EXCEPTIONS": False,
        "DATA_DIR": str(data_dir),
        "DATABASE_URL": database_url,
        "MAX_CONTENT_LENGTH": max_upload_mb * 1024 * 1024,
        "MIN_IMAGE_DIMENSION": min_dimension,
        "MAX_IMAGE_DIMENSION": max_dimension,
        "QUALITY_RECOMMENDED_MIN_DIMENSION": recommended,
        "QUALITY_MIN_BLUR_VARIANCE": min_blur,
        "QUALITY_MIN_BRIGHTNESS": min_brightness,
        "QUALITY_MAX_BRIGHTNESS": max_brightness,
        "QUALITY_MIN_CONTRAST": min_contrast,
        "QUALITY_MAX_CLIPPED_FRACTION": max_clipped,
        "LOG_LEVEL": log_level,
        "LOG_FORMAT": log_format,
        "HOST": _get(env, ENV_PREFIX + "HOST", "127.0.0.1"),
        "PORT": _get_int(env, ENV_PREFIX + "PORT", 5000),
    }
