"""Unit tests for structured logging."""

from __future__ import annotations

import json
import logging
import sys

from app.logging_config import JsonFormatter, PlainFormatter


def _make_record(message: str, **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="cheiloscan.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_valid_json_with_core_fields():
    formatted = JsonFormatter().format(_make_record("request completed"))
    payload = json.loads(formatted)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "cheiloscan.test"
    assert payload["message"] == "request completed"
    assert "timestamp" in payload


def test_json_formatter_carries_structured_extras():
    record = _make_record(
        "request completed",
        request_id="abc123",
        method="GET",
        path="/api/health",
        status=200,
        duration_ms=1.25,
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "abc123"
    assert payload["method"] == "GET"
    assert payload["status"] == 200
    assert payload["duration_ms"] == 1.25


def test_json_formatter_includes_exception_summary():
    record = _make_record("boom")
    try:
        raise ValueError("detail")
    except ValueError:
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError" in payload["exception"]
    assert "detail" in payload["exception"]


def test_plain_formatter_appends_extras_as_json():
    formatted = PlainFormatter(
        "%(levelname)s %(name)s %(message)s"
    ).format(_make_record("request completed", status=200))
    assert formatted.startswith("INFO cheiloscan.test request completed")
    assert formatted.endswith('"status": 200}')


def test_request_logging_is_structured(app, client, caplog):
    with caplog.at_level(logging.INFO, logger="cheiloscan"):
        response = client.get("/api/health")
    assert response.status_code == 200

    request_records = [
        record
        for record in caplog.records
        if record.message == "request completed"
        and hasattr(record, "request_id")
        and hasattr(record, "status")
    ]
    assert request_records, "expected a structured 'request completed' log line"
    record = request_records[-1]
    assert record.method == "GET"
    assert record.path == "/api/health"
    assert record.status == 200
    assert isinstance(record.request_id, str) and record.request_id
    assert isinstance(record.duration_ms, float)


def test_response_carries_request_id_header(client):
    response = client.get("/api/health")
    assert response.headers.get("X-Request-ID")
