"""Blueprint registration for the application."""

from __future__ import annotations

from flask import Flask

from .api.analyses import analyses_bp, analysis_bp
from .api.assets import assets_bp
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
    app.register_blueprint(analysis_bp)
    app.register_blueprint(analyses_bp)
    app.register_blueprint(assets_bp)
    app.register_blueprint(ui_bp)
