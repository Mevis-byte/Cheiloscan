"""Production WSGI server entrypoint (Waitress, single process + threads).

SQLite/WAL is designed for a single writer process; do not run multiple
workers against one data directory. Horizontal scaling requires a different
database, which is outside this project's local-first design.

Usage::

    CHEILOSCAN_ENV=production python serve.py
"""

from __future__ import annotations

from typing import Mapping

from dotenv import load_dotenv
from waitress import serve

from app import create_app
from app.config import load_config_from_env


def waitress_options(config: Mapping[str, object]) -> dict[str, object]:
    """Return Waitress settings for the configured single-process server."""
    return {
        "host": str(config["HOST"]),
        "port": int(config["PORT"]),
        "threads": int(config["THREADS"]),
        # Allow slow uploads while capping the raw body near Flask's limit.
        "channel_timeout": 120,
        "max_request_body_size": int(config["MAX_CONTENT_LENGTH"]) + 1024 * 1024,
        "connection_limit": 100,
        "cleanup_interval": 30,
        # Waitress 3 clears X-Forwarded-* by default. Production requires a
        # trusted TLS proxy that OVERWRITES those headers (see
        # deploy/nginx.conf.example); ProxyFix in app.security consumes them.
        # Keep the application reachable only from that proxy.
        "clear_untrusted_proxy_headers": False,
    }


def main() -> None:
    load_dotenv()
    config = load_config_from_env()
    application = create_app(config)

    application.logger.info(
        "starting production server",
        extra={
            "host": config["HOST"],
            "port": config["PORT"],
            "threads": config["THREADS"],
            "auth_enabled": config["AUTH_ENABLED"],
            "behind_proxy": config["BEHIND_PROXY"],
        },
    )
    serve(application, **waitress_options(config))


if __name__ == "__main__":
    main()
