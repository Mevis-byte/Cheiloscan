"""Development entrypoint.

Loads ``.env`` (python-dotenv), builds the application via the factory and
runs the Werkzeug development server bound to the configured address.

For anything beyond single-user local development, run behind a proper
WSGI server; the app is local-first by design and expects no network
exposure beyond localhost.
"""

from __future__ import annotations

from dotenv import load_dotenv

from app import create_app
from app.config import load_config_from_env

load_dotenv()
app = create_app(load_config_from_env())


if __name__ == "__main__":
    app.run(
        host=str(app.config["HOST"]),
        port=int(app.config["PORT"]),
        debug=bool(app.config["DEBUG"]),
    )
