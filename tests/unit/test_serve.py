"""Unit tests for the production server configuration."""

from __future__ import annotations

from pathlib import Path
from tempfile import mkdtemp

from serve import waitress_options

from tests.conftest import make_test_config


def test_waitress_keeps_trusted_proxy_headers():
    config = make_test_config(Path(mkdtemp()))
    config.update({"HOST": "127.0.0.1", "PORT": 5099, "THREADS": 2})

    options = waitress_options(config)

    # Waitress 3 clears X-Forwarded-* by default, which would make ProxyFix
    # and FORCE_HTTPS silently fail behind the configured TLS proxy.
    assert options["clear_untrusted_proxy_headers"] is False
    assert options["host"] == "127.0.0.1"
    assert options["port"] == 5099
    assert options["threads"] == 2
    assert (
        options["max_request_body_size"] == int(config["MAX_CONTENT_LENGTH"]) + 1024 * 1024
    )
