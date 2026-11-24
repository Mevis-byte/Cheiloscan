"""WSGI entrypoint for production servers (Gunicorn, mod_wsgi, uWSGI).

Configuration comes from environment variables; ``.env`` is loaded only when
present and never overrides real environment variables. Use ``serve.py`` for
the bundled Waitress server.
"""

from __future__ import annotations

from dotenv import load_dotenv

from app import create_app

load_dotenv()

app = application = create_app()
