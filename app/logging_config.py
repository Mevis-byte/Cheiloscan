"""Structured application logging.

Two formats are supported:

- ``json`` (default): one JSON object per line with timestamp, level,
  logger, message and any structured extras (request_id, method, path,
  status, duration_ms, exception details).
- ``plain``: human-readable single-line format for development.

Only the standard library is used; no third-party logging package.

Log caveat: unexpected exceptions include full stack traces, which can contain
SQL parameters or local paths. Logs are operational records of sensitive
research data and must be stored with the same care as the data directory.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone

from flask import Flask

# Attributes of LogRecord that are not payload; everything else passed via
# ``extra={...}`` is treated as structured payload.
_RESERVED_RECORD_ATTRS = frozenset(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime"}
# remove args? args is in __dict__ but standard; it stays reserved.


class JsonFormatter(logging.Formatter):
    """Serialize a LogRecord into a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = "".join(
                traceback.format_exception(*record.exc_info)
            )
        return json.dumps(payload, default=str)


class PlainFormatter(logging.Formatter):
    """Human-readable development format with structured extras appended."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_ATTRS and not key.startswith("_")
        }
        if record.exc_info:
            extras["exception"] = "".join(
                traceback.format_exception(*record.exc_info)
            )
        if extras:
            return f"{base} {json.dumps(extras, default=str)}"
        return base


def configure_logging(app: Flask) -> None:
    """Configure the application logger with a single, replaced handler."""
    level_name = str(app.config["LOG_LEVEL"]).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = str(app.config["LOG_FORMAT"]).lower()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if log_format == "json"
        else PlainFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(level)
    app.logger.propagate = False
