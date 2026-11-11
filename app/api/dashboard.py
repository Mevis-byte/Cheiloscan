"""Dashboard statistics endpoint.

Returns only real, currently measured counts (see
cheiloscan/services/stats.py). With no data, counts are honestly zero.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, jsonify

from ..extensions import get_database
from ..api.serializers import _iso_utc
from cheiloscan.services.stats import collect_dashboard_stats

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@dashboard_bp.get("/stats")
def stats():
    database = get_database()
    data_dir = Path(current_app.config["DATA_DIR"])
    with database.session() as session:
        stats = collect_dashboard_stats(session, data_dir)
    return jsonify(
        {
            "samples": {
                "total": stats.samples_total,
                "active": stats.samples_active,
            },
            "images": {"total": stats.images_total},
            "analyses": {
                "total": stats.analyses_total,
                "by_status": stats.analyses_by_status,
            },
            "comparisons": {
                "total": stats.comparisons_total,
                "by_status": stats.comparisons_by_status,
            },
            "storage": {"bytes": stats.storage_bytes},
            "database": {"schema_version": stats.schema_version},
            "generated_at": _iso_utc(stats.generated_at),
        }
    )
