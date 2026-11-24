"""Application configuration.

Environment-driven configuration with fail-fast validation. The canonical
variable names are documented in ``.env.example``. Values are read from the
process environment (``run.py`` loads ``.env`` via python-dotenv before the
application factory is called).

When Vercel is detected (``VERCEL=1`` or ``VERCEL_ENV``), production mode,
trusted-proxy TLS handling, Postgres and Vercel Blob become the defaults so a
correctly provisioned Vercel project works without extra flags.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping

ENV_PREFIX = "CHEILOSCAN_"

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
VALID_LOG_FORMATS = {"json", "plain"}
VALID_ENVIRONMENTS = {"development", "production"}
VALID_STORAGE_BACKENDS = {"local", "vercel_blob"}
VALID_BLOB_ACCESS = {"public", "private"}
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}

DEFAULT_DATA_DIR = "data"
DEFAULT_MAX_UPLOAD_MB = 25
# Vercel Functions accept 4.5 MB request bodies by default; stay just below it
# so our own 413 is deterministic instead of the platform's opaque error.
VERCEL_DEFAULT_MAX_UPLOAD_MB = 4
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
DEFAULT_THREADS = 2
DEFAULT_MAX_IMAGE_PIXELS = 20_000_000
DEFAULT_AUTH_MAX_FAILURES = 10
DEFAULT_AUTH_LOCKOUT_SECONDS = 60
MIN_SECRET_KEY_LENGTH = 32
MAX_UPLOAD_MB = 100
MAX_IMAGE_DIMENSION_LIMIT = 20_000

#: Werkzeug hash methods accepted for CHEILOSCAN_AUTH_PASSWORD_HASH.
_PASSWORD_HASH_PREFIX = re.compile(r"^(?:scrypt|pbkdf2|argon2)[:$]", re.IGNORECASE)

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
    "STORAGE_BACKEND",
    "STORAGE_PREFIX",
    "BLOB_ACCESS",
    "MAX_CONTENT_LENGTH",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "MIN_IMAGE_DIMENSION",
    "MAX_IMAGE_DIMENSION",
    "MAX_IMAGE_PIXELS",
    "QUALITY_RECOMMENDED_MIN_DIMENSION",
    "QUALITY_MIN_BLUR_VARIANCE",
    "QUALITY_MIN_BRIGHTNESS",
    "QUALITY_MAX_BRIGHTNESS",
    "QUALITY_MIN_CONTRAST",
    "QUALITY_MAX_CLIPPED_FRACTION",
    "HOST",
    "PORT",
    "THREADS",
    "AUTH_ENABLED",
    "AUTH_USERNAME",
    "AUTH_PASSWORD_HASH",
    "AUTH_MAX_FAILURES",
    "AUTH_LOCKOUT_SECONDS",
    "BEHIND_PROXY",
    "TRUSTED_PROXY_COUNT",
    "FORCE_HTTPS",
    "ALLOWED_HOSTS",
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


def _get_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _get(env, name, str(default)).strip().lower()
    if raw in TRUE_VALUES:
        return True
    if raw in FALSE_VALUES:
        return False
    raise ConfigurationError(f"{name} must be a boolean, got {raw!r}")


def _get_hosts(env: Mapping[str, str], name: str) -> tuple[str, ...]:
    raw = _get(env, name)
    hosts = tuple(
        dict.fromkeys(
            item.strip().lower()
            for item in raw.split(",")
            if item.strip()
        )
    )
    for host in hosts:
        if any(character.isspace() for character in host):
            raise ConfigurationError(f"{name} contains an invalid host: {host!r}")
    return hosts


def is_vercel(env: Mapping[str, str]) -> bool:
    """Return whether configuration is being loaded inside Vercel Functions."""
    return _get(env, "VERCEL").lower() in TRUE_VALUES or bool(_get(env, "VERCEL_ENV"))


def vercel_hosts(env: Mapping[str, str]) -> tuple[str, ...]:
    """Hosts Vercel advertises for the current project/deployment."""
    hosts: list[str] = []
    for name in (
        "VERCEL_PROJECT_PRODUCTION_URL",
        "VERCEL_BRANCH_URL",
        "VERCEL_URL",
    ):
        raw = _get(env, name).strip()
        if not raw:
            continue
        host = raw.split("://", 1)[-1].split("/", 1)[0].strip().lower()
        if host and all(not character.isspace() for character in host):
            hosts.append(host)
    return tuple(dict.fromkeys(hosts))


def normalize_database_url(url: str) -> str:
    """Use psycopg explicitly for generic Postgres URLs.

    SQLAlchemy's default ``postgresql://`` driver is psycopg2, which is not in
    the dependency set. Neon and Vercel Marketplace hand out generic URLs, so
    normalizing here prevents a driver-not-installed error at cold start.
    """
    for legacy in ("postgresql://", "postgres://"):
        if url.startswith(legacy):
            return "postgresql+psycopg://" + url[len(legacy) :]
    return url


def default_database_url(data_dir: Path) -> str:
    """SQLite URL for ``<data_dir>/db/app.sqlite`` (absolute, POSIX form)."""
    return "sqlite:///" + (data_dir / "db" / "app.sqlite").as_posix()


def load_config_from_env(
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Build the application configuration mapping from the environment."""
    if env is None:
        env = os.environ

    on_vercel = is_vercel(env)
    environment = _get(
        env, ENV_PREFIX + "ENV", "production" if on_vercel else "development"
    ).lower()
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

    default_upload_mb = (
        VERCEL_DEFAULT_MAX_UPLOAD_MB if on_vercel else DEFAULT_MAX_UPLOAD_MB
    )
    max_upload_mb = _get_int(
        env, ENV_PREFIX + "MAX_UPLOAD_MB", default_upload_mb
    )
    if not 1 <= max_upload_mb <= MAX_UPLOAD_MB:
        raise ConfigurationError(
            f"CHEILOSCAN_MAX_UPLOAD_MB must be between 1 and {MAX_UPLOAD_MB}, "
            f"got {max_upload_mb}"
        )

    min_dimension = _get_int(
        env, ENV_PREFIX + "MIN_IMAGE_DIMENSION", DEFAULT_MIN_IMAGE_DIMENSION
    )
    max_dimension = _get_int(
        env, ENV_PREFIX + "MAX_IMAGE_DIMENSION", DEFAULT_MAX_IMAGE_DIMENSION
    )
    max_pixels = _get_int(
        env, ENV_PREFIX + "MAX_IMAGE_PIXELS", DEFAULT_MAX_IMAGE_PIXELS
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
    if max_dimension > MAX_IMAGE_DIMENSION_LIMIT:
        raise ConfigurationError(
            "CHEILOSCAN_MAX_IMAGE_DIMENSION must not exceed "
            f"{MAX_IMAGE_DIMENSION_LIMIT} pixels"
        )
    if not min_dimension * min_dimension <= max_pixels <= 100_000_000:
        raise ConfigurationError(
            "CHEILOSCAN_MAX_IMAGE_PIXELS must be at least the square of the "
            "minimum dimension and at most 100000000"
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

    database_url = normalize_database_url(
        _get(env, ENV_PREFIX + "DATABASE_URL") or default_database_url(data_dir)
    )
    if on_vercel and not database_url.startswith("postgresql+psycopg://"):
        raise ConfigurationError(
            "Vercel deployments require CHEILOSCAN_DATABASE_URL with a "
            "persistent Postgres/Neon connection string; SQLite cannot persist "
            "on Vercel's ephemeral filesystem"
        )

    storage_backend = _get(
        env,
        ENV_PREFIX + "STORAGE_BACKEND",
        "vercel_blob" if on_vercel else "local",
    ).lower()
    if storage_backend not in VALID_STORAGE_BACKENDS:
        raise ConfigurationError(
            f"CHEILOSCAN_STORAGE_BACKEND must be one of "
            f"{sorted(VALID_STORAGE_BACKENDS)}, got {storage_backend!r}"
        )
    storage_prefix = _get(env, ENV_PREFIX + "STORAGE_PREFIX", "cheiloscan")
    storage_prefix = storage_prefix.strip("/")
    if (
        "\\" in storage_prefix
        or ".." in storage_prefix.split("/")
        or not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", storage_prefix)
    ):
        raise ConfigurationError(
            "CHEILOSCAN_STORAGE_PREFIX must be a safe object-key prefix "
            "(letters, digits, '.', '_', '-' and '/' only)"
        )
    blob_access = _get(env, ENV_PREFIX + "BLOB_ACCESS", "private").lower()
    if blob_access not in VALID_BLOB_ACCESS:
        raise ConfigurationError(
            f"CHEILOSCAN_BLOB_ACCESS must be one of {sorted(VALID_BLOB_ACCESS)}, "
            f"got {blob_access!r}"
        )
    if storage_backend == "vercel_blob" and not any(
        _get(env, name)
        for name in (
            "BLOB_READ_WRITE_TOKEN",
            "VERCEL_BLOB_READ_WRITE_TOKEN",
            "BLOB_STORE_ID",
        )
    ):
        raise ConfigurationError(
            "Vercel Blob storage requires BLOB_READ_WRITE_TOKEN (or "
            "BLOB_STORE_ID with Vercel OIDC) to be set"
        )

    secret_key = _get(env, ENV_PREFIX + "SECRET_KEY")
    if environment == "production" and not secret_key:
        raise ConfigurationError(
            "CHEILOSCAN_SECRET_KEY must be set when CHEILOSCAN_ENV=production"
        )
    if secret_key and len(secret_key) < MIN_SECRET_KEY_LENGTH:
        raise ConfigurationError(
            f"CHEILOSCAN_SECRET_KEY must contain at least {MIN_SECRET_KEY_LENGTH} "
            "characters"
        )
    if not secret_key:
        # Development fallback: ephemeral per-process key. Only acceptable
        # because no sessions or cookies with security guarantees exist yet.
        secret_key = os.urandom(32).hex()

    username = _get(env, ENV_PREFIX + "AUTH_USERNAME")
    password_hash = _get(env, ENV_PREFIX + "AUTH_PASSWORD_HASH")
    if password_hash and not _PASSWORD_HASH_PREFIX.match(password_hash):
        raise ConfigurationError(
            "CHEILOSCAN_AUTH_PASSWORD_HASH must be a Werkzeug hash generated "
            "with `python -m app.security hash-password`"
        )
    if bool(username) != bool(password_hash):
        raise ConfigurationError(
            "CHEILOSCAN_AUTH_USERNAME and CHEILOSCAN_AUTH_PASSWORD_HASH must "
            "be set together"
        )
    if environment == "production" and not (username and password_hash):
        raise ConfigurationError(
            "CHEILOSCAN_AUTH_USERNAME and CHEILOSCAN_AUTH_PASSWORD_HASH are "
            "required when CHEILOSCAN_ENV=production"
        )
    # Production always requires HTTP Basic auth: the app holds
    # biometric-adjacent research data and has no other access control.
    auth_enabled = environment == "production" or bool(username)

    behind_proxy = _get_bool(env, ENV_PREFIX + "BEHIND_PROXY", on_vercel)
    trusted_proxy_count = _get_int(
        env, ENV_PREFIX + "TRUSTED_PROXY_COUNT", 1
    )
    if not 1 <= trusted_proxy_count <= 5:
        raise ConfigurationError(
            "CHEILOSCAN_TRUSTED_PROXY_COUNT must be between 1 and 5"
        )
    force_https = _get_bool(env, ENV_PREFIX + "FORCE_HTTPS", on_vercel)
    allowed_hosts = _get_hosts(env, ENV_PREFIX + "ALLOWED_HOSTS")
    if on_vercel and not allowed_hosts:
        # Derive the deployment host(s) so a fresh Vercel project works before
        # a custom domain is configured. Custom domains must still be listed
        # explicitly in CHEILOSCAN_ALLOWED_HOSTS.
        allowed_hosts = vercel_hosts(env)
    if force_https and not behind_proxy:
        raise ConfigurationError(
            "CHEILOSCAN_FORCE_HTTPS requires CHEILOSCAN_BEHIND_PROXY=1 because "
            "TLS is terminated by a trusted reverse proxy"
        )
    if force_https and not allowed_hosts:
        raise ConfigurationError(
            "CHEILOSCAN_ALLOWED_HOSTS must be set when CHEILOSCAN_FORCE_HTTPS=1"
        )
    if environment == "production" and not (behind_proxy and force_https and allowed_hosts):
        raise ConfigurationError(
            "production requires CHEILOSCAN_BEHIND_PROXY=1, "
            "CHEILOSCAN_FORCE_HTTPS=1 and CHEILOSCAN_ALLOWED_HOSTS: terminate "
            "TLS at a trusted reverse proxy before exposing this service"
        )

    host = _get(env, ENV_PREFIX + "HOST", DEFAULT_HOST)
    port = _get_int(env, ENV_PREFIX + "PORT", DEFAULT_PORT)
    if not 1 <= port <= 65535:
        raise ConfigurationError("CHEILOSCAN_PORT must be between 1 and 65535")
    if environment == "development" and host not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigurationError(
            "DEBUG is enabled in development; CHEILOSCAN_HOST must be a "
            "loopback address. Use CHEILOSCAN_ENV=production behind a proxy."
        )
    threads = _get_int(env, ENV_PREFIX + "THREADS", DEFAULT_THREADS)
    if not 1 <= threads <= 4:
        raise ConfigurationError(
            "CHEILOSCAN_THREADS must be between 1 and 4 (single SQLite writer)"
        )
    auth_max_failures = _get_int(
        env, ENV_PREFIX + "AUTH_MAX_FAILURES", DEFAULT_AUTH_MAX_FAILURES
    )
    auth_lockout_seconds = _get_int(
        env, ENV_PREFIX + "AUTH_LOCKOUT_SECONDS", DEFAULT_AUTH_LOCKOUT_SECONDS
    )
    if not 1 <= auth_max_failures <= 100:
        raise ConfigurationError("CHEILOSCAN_AUTH_MAX_FAILURES must be 1..100")
    if not 1 <= auth_lockout_seconds <= 3600:
        raise ConfigurationError("CHEILOSCAN_AUTH_LOCKOUT_SECONDS must be 1..3600")

    return {
        "SECRET_KEY": secret_key,
        "DEBUG": environment == "development",
        "TESTING": False,
        # Keep Flask from swallowing exceptions past our centralized handlers.
        "PROPAGATE_EXCEPTIONS": False,
        "DATA_DIR": str(data_dir),
        "DATABASE_URL": database_url,
        "STORAGE_BACKEND": storage_backend,
        "STORAGE_PREFIX": storage_prefix,
        "BLOB_ACCESS": blob_access,
        "MAX_CONTENT_LENGTH": max_upload_mb * 1024 * 1024,
        "MIN_IMAGE_DIMENSION": min_dimension,
        "MAX_IMAGE_DIMENSION": max_dimension,
        "MAX_IMAGE_PIXELS": max_pixels,
        "QUALITY_RECOMMENDED_MIN_DIMENSION": recommended,
        "QUALITY_MIN_BLUR_VARIANCE": min_blur,
        "QUALITY_MIN_BRIGHTNESS": min_brightness,
        "QUALITY_MAX_BRIGHTNESS": max_brightness,
        "QUALITY_MIN_CONTRAST": min_contrast,
        "QUALITY_MAX_CLIPPED_FRACTION": max_clipped,
        "LOG_LEVEL": log_level,
        "LOG_FORMAT": log_format,
        "HOST": host,
        "PORT": port,
        "THREADS": threads,
        "AUTH_ENABLED": auth_enabled,
        "AUTH_USERNAME": username,
        "AUTH_PASSWORD_HASH": password_hash,
        "AUTH_MAX_FAILURES": auth_max_failures,
        "AUTH_LOCKOUT_SECONDS": auth_lockout_seconds,
        "BEHIND_PROXY": behind_proxy,
        "TRUSTED_PROXY_COUNT": trusted_proxy_count,
        "FORCE_HTTPS": force_https,
        "ALLOWED_HOSTS": allowed_hosts,
    }
