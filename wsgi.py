"""WSGI entrypoint for production servers and Vercel Functions.

Configuration comes from environment variables; ``.env`` is loaded only when
present and never overrides real environment variables. Use ``serve.py`` for
the bundled Waitress server. Vercel resolves ``tool.vercel.entrypoint`` to this
module's ``app`` object.
"""

from __future__ import annotations

from dotenv import load_dotenv

from app import create_app

load_dotenv()

app = application = create_app()
