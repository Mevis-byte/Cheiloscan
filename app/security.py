"""HTTP security controls for deployed CheiloScan instances.

The application has no cookie-based sessions: authentication is HTTP Basic,
validated against a Werkzeug password hash from the environment. Basic auth is
sent by the browser on every same-origin request, including image fetches, so
the whole UI (and the asset endpoints) stays protected.

Additional controls:

- trusted-proxy headers are only honoured when explicitly enabled;
- ``CHEILOSCAN_ALLOWED_HOSTS`` blocks unexpected Host headers;
- unsafe methods require a same-origin ``Origin`` header when one is present;
- ``CHEILOSCAN_FORCE_HTTPS`` redirects to HTTPS behind a TLS terminator;
- strict security headers and conservative cache policies are applied to all
  responses.

Run ``python -m app.security hash-password`` to generate a password hash.
"""

from __future__ import annotations

import getpass
import hmac
import sys
import threading
import time
from urllib.parse import quote, urlsplit

from flask import Flask, Response, current_app, g, jsonify, redirect, request
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

#: Probes that must stay public so a load balancer can check liveness.
PUBLIC_PATHS = frozenset({"/api/health/live"})

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: In-process failed-login counter (single WSGI process by design).
_FAILED_ATTEMPTS: dict[str, tuple[int, float]] = {}
_FAILED_ATTEMPTS_LOCK = threading.Lock()

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; "
        "object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def install_security(app: Flask) -> None:
    """Attach proxy handling, request checks and response headers."""
    if app.config["BEHIND_PROXY"]:
        trusted = int(app.config["TRUSTED_PROXY_COUNT"])
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=trusted,
            x_proto=trusted,
            x_host=trusted,
            x_port=trusted,
        )

    @app.before_request
    def _enforce_security() -> Response | None:
        # Liveness is deliberately proxy-agnostic: container/load-balancer
        # probes call it over plain loopback HTTP with an internal Host header.
        # It exposes no application state, so it bypasses Host/TLS checks too.
        if request.path in PUBLIC_PATHS:
            return None
        return (
            _check_host()
            or _check_https()
            or _check_origin()
            or _check_authentication()
        )

    @app.after_request
    def _apply_security_headers(response: Response) -> Response:
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        _apply_cache_policy(response)
        return response


def _error(
    code: str, message: str, status: int, headers: dict[str, str] | None = None
) -> Response:
    body: dict[str, object] = {"error": {"code": code, "message": message}}
    request_id = g.get("request_id")
    if request_id:
        body["request_id"] = request_id
    response = jsonify(body)
    response.status_code = status
    if headers:
        response.headers.update(headers)
    return response


def _hostname(netloc: str) -> str:
    """Return the host part of ``netloc``, preserving bracketed IPv6 hosts."""
    if netloc.startswith("["):
        closing = netloc.find("]")
        return netloc[: closing + 1] if closing != -1 else netloc
    return netloc.split(":", 1)[0]


def _origin_tuple(scheme: str, netloc: str) -> tuple[str, str, int] | None:
    """Normalize ``(scheme, host, port)`` using scheme-default ports."""
    if scheme not in {"http", "https"}:
        return None
    netloc = netloc.lower()
    host = _hostname(netloc)
    remainder = netloc[len(host) :]
    port: int | None = None
    if remainder.startswith(":"):
        raw_port = remainder[1:]
        if not raw_port.isdigit():
            return None
        port = int(raw_port)
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, host, port


def _current_origin() -> tuple[str, str, int] | None:
    scheme = "https" if request.is_secure else "http"
    return _origin_tuple(scheme, (request.host or "").lower())


def _check_host() -> Response | None:
    allowed = current_app.config["ALLOWED_HOSTS"]
    if not allowed:
        return None
    host = (request.host or "").lower()
    bare = _hostname(host)
    if host in allowed or bare in allowed:
        return None
    return _error("invalid_host", "unexpected Host header", 400)


def _check_https() -> Response | None:
    if not current_app.config["FORCE_HTTPS"] or request.is_secure:
        return None
    # request.query_string is raw bytes; re-encode so %-escapes stay intact.
    query = request.query_string.decode("ascii", errors="surrogateescape")
    target = f"https://{request.host}{quote(request.path, safe='/%')}"
    if query:
        target += f"?{query}"
    return redirect(target, code=308)


def _check_origin() -> Response | None:
    if request.method not in UNSAFE_METHODS:
        return None

    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site and fetch_site not in {"same-origin", "none"}:
        return _error("invalid_origin", "cross-origin requests are not allowed", 403)

    origin = request.headers.get("Origin")
    if not origin:
        # Non-browser clients (curl, scripts) cannot be CSRF'd this way.
        return None
    parts = urlsplit(origin)
    origin_tuple = _origin_tuple(parts.scheme, parts.netloc)
    same_origin = origin_tuple is not None and origin_tuple == _current_origin()
    if not same_origin:
        return _error("invalid_origin", "cross-origin requests are not allowed", 403)
    return None


def _check_authentication() -> Response | None:
    if not current_app.config["AUTH_ENABLED"]:
        return None
    if request.path in PUBLIC_PATHS:
        return None

    client = request.remote_addr or "unknown"
    if _is_rate_limited(client):
        return _error(
            "too_many_attempts",
            "too many failed authentication attempts; try again later",
            429,
            {"Retry-After": str(int(current_app.config["AUTH_LOCKOUT_SECONDS"]))},
        )

    credentials = request.authorization
    valid = False
    if credentials is not None and credentials.type.lower() == "basic":
        expected_user = str(current_app.config["AUTH_USERNAME"])
        supplied_user = credentials.username or ""
        supplied_password = credentials.password or ""
        valid = hmac.compare_digest(supplied_user, expected_user)
        if valid:
            try:
                valid = check_password_hash(
                    str(current_app.config["AUTH_PASSWORD_HASH"]), supplied_password
                )
            except ValueError:
                valid = False
    if valid:
        _clear_failures(client)
        return None

    _record_failure(client)
    return _error(
        "authentication_required",
        "valid credentials are required",
        401,
        {"WWW-Authenticate": 'Basic realm="CheiloScan", charset="UTF-8"'},
    )


def _lockout_window() -> float:
    return float(current_app.config["AUTH_LOCKOUT_SECONDS"])


def _is_rate_limited(client: str) -> bool:
    now = time.monotonic()
    with _FAILED_ATTEMPTS_LOCK:
        count, first = _FAILED_ATTEMPTS.get(client, (0, now))
        if now - first >= _lockout_window():
            _FAILED_ATTEMPTS.pop(client, None)
            return False
        return count >= int(current_app.config["AUTH_MAX_FAILURES"])


def _record_failure(client: str) -> None:
    now = time.monotonic()
    window = _lockout_window()
    with _FAILED_ATTEMPTS_LOCK:
        count, first = _FAILED_ATTEMPTS.get(client, (0, now))
        if now - first >= window:
            count, first = 0, now
        _FAILED_ATTEMPTS[client] = (count + 1, first)
        # Bound memory: drop the oldest entries when the table grows large.
        if len(_FAILED_ATTEMPTS) > 1000:
            for key in list(_FAILED_ATTEMPTS)[:100]:
                _FAILED_ATTEMPTS.pop(key, None)


def _clear_failures(client: str) -> None:
    with _FAILED_ATTEMPTS_LOCK:
        _FAILED_ATTEMPTS.pop(client, None)


def _apply_cache_policy(response: Response) -> None:
    path = request.path
    if path.startswith("/api/assets/") and response.status_code == 200:
        # The asset endpoint already marks sensitive images private/no-store.
        response.headers.setdefault("Cache-Control", "private, no-store")
    elif path.startswith("/api/") or response.mimetype == "application/json":
        response.headers["Cache-Control"] = "no-store"
    else:
        # UI and static files must be revalidated after a deployment.
        response.headers.setdefault("Cache-Control", "no-cache")


def main() -> int:
    """CLI helper: ``python -m app.security hash-password``."""
    if len(sys.argv) != 2 or sys.argv[1] != "hash-password":
        print("usage: python -m app.security hash-password", file=sys.stderr)
        return 2
    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("passwords do not match", file=sys.stderr)
        return 2
    if len(password) < 12:
        print("password must contain at least 12 characters", file=sys.stderr)
        return 2
    print(generate_password_hash(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
