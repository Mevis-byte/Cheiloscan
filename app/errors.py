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

from cheiloscan.imaging.pipeline import InvalidParameterError
from cheiloscan.services.intake import IntakeError
from cheiloscan.storage.asset_store import StorageError
from cheiloscan.services.processing import ProcessingError

#: HTTP status for each stable intake/processing error code.
_DOMAIN_STATUS = {
    # Intake.
    "file_too_large": 413,
    "unsupported_format": 415,
    "invalid_image": 400,
    "image_dimensions_invalid": 422,
    "duplicate_image": 409,
    "invalid_sample_metadata": 400,
    "sample_code_conflict": 409,
    # Processing.
    "sample_not_found": 404,
    "sample_has_no_image": 409,
    "analysis_not_found": 404,
    "processing_error": 500,
    "invalid_parameters": 400,
}


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
        if exc.code == 413:
            # Keep one code for both Flask's body limit and service checks.
            code = "file_too_large"
        message = exc.description or exc.name or "request failed"
        return _envelope(code, message, exc.code or 500)

    @app.errorhandler(InvalidParameterError)
    def handle_invalid_parameters(exc: InvalidParameterError):
        return _envelope(
            "invalid_parameters",
            "invalid processing parameters",
            400,
            details={"errors": exc.errors},
        )

    @app.errorhandler(IntakeError)
    def handle_intake_error(exc: IntakeError):
        status = _DOMAIN_STATUS.get(exc.code, 400)
        return _envelope(
            exc.code,
            exc.message,
            status,
            details=exc.details or None,
        )

    @app.errorhandler(ProcessingError)
    def handle_processing_error(exc: ProcessingError):
        status = _DOMAIN_STATUS.get(exc.code, 400)
        return _envelope(
            exc.code,
            exc.message,
            status,
            details=exc.details or None,
        )

    @app.errorhandler(StorageError)
    def handle_storage_error(exc: StorageError):
        app.logger.exception("storage error", extra={"request_id": g.get("request_id")})
        return _envelope(
            "storage_error",
            "A storage error occurred while processing the request.",
            500,
        )

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
