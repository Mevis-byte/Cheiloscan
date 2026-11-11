"""Blueprint registration for the application."""

from __future__ import annotations

from flask import Flask

from .api.comparisons import comparisons_bp
from .api.dashboard import dashboard_bp
from .api.health import health_bp
from .api.samples import samples_bp
from .ui import ui_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(health_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(samples_bp)
    app.register_blueprint(comparisons_bp)
    app.register_blueprint(ui_bp)
