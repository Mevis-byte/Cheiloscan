"""Flask application package (HTTP layer only).

This package contains routes, request handling, serialization and error
responses. Business logic lives in the ``cheiloscan`` package, which must
never import from here (enforced by tests/unit/test_import_rules.py).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from flask import Flask, g, request

from .config import CONFIG_KEYS, load_config_from_env
from .errors import register_error_handlers
from .logging_config import configure_logging
from .routes import register_blueprints
from cheiloscan.db.session import Database
from cheiloscan.storage import ensure_storage_directories
from cheiloscan.storage.asset_store import AssetStore

APP_NAME = "cheiloscan"


def create_app(config: Mapping[str, object] | None = None) -> Flask:
    """Application factory.

    ``config`` may be an explicit mapping (used by tests); when omitted the
    configuration is loaded from the environment via ``load_config_from_env``.
    """
    app = Flask(APP_NAME, static_folder="../web", static_url_path="")
    app.config.update(config if config is not None else load_config_from_env())

    missing = [key for key in CONFIG_KEYS if key not in app.config]
    if missing:
        raise ValueError(
            f"create_app received incomplete configuration; missing keys: {missing}"
        )

    configure_logging(app)

    # Storage layout + database schema (both idempotent, safe on every start).
    ensure_storage_directories(Path(app.config["DATA_DIR"]))
    database = Database(app.config["DATABASE_URL"])
    database.init_schema()
    app.extensions["database"] = database
    app.extensions["asset_store"] = AssetStore(Path(app.config["DATA_DIR"]))

    register_blueprints(app)
    register_error_handlers(app)
    _register_request_hooks(app)
    return app


def _register_request_hooks(app: Flask) -> None:
    @app.before_request
    def _begin_request() -> None:
        g.request_id = uuid4().hex
        g.request_started_at = time.perf_counter()

    @app.after_request
    def _finish_request(response):
        started = g.get("request_started_at")
        duration_ms = (
            round((time.perf_counter() - started) * 1000.0, 3)
            if started is not None
            else None
        )
        app.logger.info(
            "request completed",
            extra={
                "request_id": g.get("request_id"),
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = g.get("request_id", "")
        return response
