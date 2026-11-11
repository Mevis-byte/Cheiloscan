"""Centralized exception handling.

Every failure is returned in a consistent JSON envelope::

    {"error": {"code": "<snake_case_code>", "message": "<human text>"},
     "request_id": "<correlation id>"}

Rules:

- HTTP exceptions (404, 405, 400, 413, ...) use their status code and a
  snake_case code derived from the Werkzeug name.
- Database errors (SQLAlchemyError) become 500 ``database_error`` with a
  generic message; internals (driver errors, SQL, paths) are never leaked
  to clients - they are logged server-side with the full stack trace.
- Unexpected exceptions become 500 ``internal_error`` and are logged.
"""

from __future__ import annotations

import re

from flask import Flask, g, jsonify
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException


def _snake_case(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _envelope(code: str, message: str, status: int, details=None):
    body: dict = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    request_id = g.get("request_id")
    if request_id:
        body["request_id"] = request_id
    return jsonify(body), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):
        code = _snake_case(exc.name or "error") or "error"
        message = exc.description or exc.name or "request failed"
        return _envelope(code, message, exc.code or 500)

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(exc: SQLAlchemyError):
        app.logger.exception("database error", extra={"request_id": g.get("request_id")})
        return _envelope(
            "database_error",
            "A database error occurred while processing the request.",
            500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        app.logger.exception(
            "unhandled exception", extra={"request_id": g.get("request_id")}
        )
        return _envelope(
            "internal_error",
            "An unexpected error occurred while processing the request.",
            500,
        )
