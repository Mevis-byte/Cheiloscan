"""Integration tests for production HTTP security controls."""

from __future__ import annotations

from base64 import b64encode

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from app.security import _FAILED_ATTEMPTS
from tests.conftest import make_test_config

PASSWORD = "correct-horse-battery-staple"
USERNAME = "researcher"


@pytest.fixture
def secure_app(tmp_path) -> Flask:
    from app import create_app

    config = make_test_config(tmp_path / "data")
    config.update(
        {
            "AUTH_ENABLED": True,
            "AUTH_USERNAME": USERNAME,
            "AUTH_PASSWORD_HASH": generate_password_hash(PASSWORD),
            "ALLOWED_HOSTS": ("localhost",),
            "BEHIND_PROXY": True,
            "FORCE_HTTPS": False,
            "TRUSTED_PROXY_COUNT": 1,
            "AUTH_MAX_FAILURES": 5,
            "AUTH_LOCKOUT_SECONDS": 60,
        }
    )
    _FAILED_ATTEMPTS.clear()
    application = create_app(config)
    yield application
    application.extensions["database"].dispose()
    _FAILED_ATTEMPTS.clear()


@pytest.fixture
def secure_client(secure_app):
    return secure_app.test_client()


def _auth(username: str = USERNAME, password: str = PASSWORD) -> dict[str, str]:
    token = b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_liveness_is_public(secure_client):
    response = secure_client.get("/api/health/live")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "app": "cheiloscan"}


def test_liveness_bypasses_public_host_and_https_checks(secure_client, secure_app):
    secure_app.config["FORCE_HTTPS"] = True
    response = secure_client.get(
        "/api/health/live", headers={"Host": "internal-probe"}
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_protected_routes_require_basic_auth(secure_client):
    for path in ("/", "/api/dashboard/stats", "/api/samples"):
        response = secure_client.get(path)
        assert response.status_code == 401
        assert response.get_json()["error"]["code"] == "authentication_required"
        assert "Basic" in response.headers["WWW-Authenticate"]


def test_valid_credentials_grant_access(secure_client):
    assert secure_client.get("/", headers=_auth()).status_code == 200
    assert secure_client.get("/api/samples", headers=_auth()).status_code == 200


def test_wrong_credentials_are_rejected(secure_client):
    response = secure_client.get("/", headers=_auth(password="wrong-password"))
    assert response.status_code == 401


def test_security_headers_and_cache_policy(secure_client):
    response = secure_client.get("/api/samples", headers=_auth())
    assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"

    page = secure_client.get("/", headers=_auth())
    assert page.headers["Cache-Control"] == "no-cache"
    assert page.headers["Cross-Origin-Opener-Policy"] == "same-origin"


def test_hsts_is_sent_only_on_secure_requests(secure_client):
    plain = secure_client.get(
        "/api/samples", headers={**_auth(), "X-Forwarded-Proto": "http"}
    )
    assert "Strict-Transport-Security" not in plain.headers

    secure = secure_client.get(
        "/api/samples", headers={**_auth(), "X-Forwarded-Proto": "https"}
    )
    assert secure.headers["Strict-Transport-Security"].startswith(
        "max-age=31536000"
    )


def test_host_allowlist_blocks_unexpected_hosts(secure_client):
    response = secure_client.get(
        "/", headers={**_auth(), "Host": "attacker.example.org"}
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_host"


def test_https_is_enforced(secure_client, secure_app):
    secure_app.config["FORCE_HTTPS"] = True
    response = secure_client.get("/samples?limit=1")
    assert response.status_code == 308
    assert response.headers["Location"].startswith("https://localhost/samples?limit=1")


def test_cross_origin_post_is_rejected(secure_client):
    response = secure_client.post(
        "/api/analysis/missing/process",
        headers={**_auth(), "Origin": "http://evil.example.org"},
        json={},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "invalid_origin"


def test_same_origin_post_reaches_the_route(secure_client):
    response = secure_client.post(
        "/api/analysis/missing/process",
        headers={**_auth(), "Origin": "http://localhost"},
        json={},
    )
    assert response.status_code == 404  # unknown run, not a security rejection


def test_failed_attempts_are_rate_limited(secure_client):
    for _ in range(5):
        assert (
            secure_client.get("/", headers=_auth(password="bad-password")).status_code
            == 401
        )
    limited = secure_client.get("/", headers=_auth())
    assert limited.status_code == 429
    assert limited.get_json()["error"]["code"] == "too_many_attempts"
