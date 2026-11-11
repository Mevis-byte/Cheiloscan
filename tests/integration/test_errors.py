"""Integration tests: centralized error handling and JSON envelopes."""

from __future__ import annotations

import json

from cheiloscan.db.session import Database


def test_unknown_api_route_returns_json_envelope(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    body = response.get_json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"]


def test_method_not_allowed_returns_json_envelope(client):
    response = client.post("/api/samples")
    assert response.status_code == 405
    body = response.get_json()
    assert body["error"]["code"] == "method_not_allowed"


def test_database_error_returns_generic_envelope(client, app, tmp_path):
    broken = Database(
        "sqlite:///" + (tmp_path / "missing-dir" / "x.db").as_posix()
    )
    try:
        original = app.extensions["database"]
        app.extensions["database"] = broken

        response = client.get("/api/dashboard/stats")
        assert response.status_code == 500
        body = response.get_json()
        assert body["error"]["code"] == "database_error"
        # Internals (driver messages, SQL, paths) must not leak to clients.
        serialized = json.dumps(body)
        assert "unable to open" not in serialized.lower()
        assert str(tmp_path) not in serialized
        assert body["request_id"]
    finally:
        broken.dispose()
        app.extensions["database"] = original


def test_all_error_responses_share_the_envelope_shape(client):
    responses = (
        client.get("/api/does-not-exist"),
        client.post("/api/samples"),
        client.get("/api/samples?limit=abc"),
    )
    for response in responses:
        body = response.get_json()
        assert set(body) == {"error", "request_id"}
        assert set(body["error"]) == {"code", "message"}
