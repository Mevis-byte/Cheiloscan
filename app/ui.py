"""Static frontend routes (serves the pages in ``web/``).

No server-side templating by design (docs/ARCHITECTURE.md §7): the UI is
plain HTML/CSS/JS talking to the JSON API via fetch, keeping the HTTP layer
thin and the app fully offline-capable.
"""

from __future__ import annotations

from flask import Blueprint, current_app, request

ui_bp = Blueprint("ui", __name__)

_PAGES = {
    "/": "index.html",
    "/samples": "samples.html",
    "/analyses": "analyses.html",
    "/comparisons": "comparisons.html",
}


@ui_bp.get("/")
@ui_bp.get("/samples")
@ui_bp.get("/analyses")
@ui_bp.get("/comparisons")
def page():
    return current_app.send_static_file(_PAGES[request.path])


@ui_bp.get("/analysis/<analysis_id>")
def analysis_detail(analysis_id: str):
    """Analysis detail page; the run id is read from the URL by the client."""
    return current_app.send_static_file("analysis.html")
