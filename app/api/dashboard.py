"""Dashboard statistics endpoint.

Returns only real, currently measured counts (see
cheiloscan/services/stats.py). With no data, counts are honestly zero.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from ..extensions import get_asset_store, get_database
from ..api.serializers import _iso_utc
from cheiloscan.services.stats import collect_dashboard_stats

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@dashboard_bp.get("/stats")
def stats():
    database = get_database()
    storage_bytes = int(
        get_asset_store().describe().get("bytes_used", 0) or 0
    )
    with database.session() as session:
        stats = collect_dashboard_stats(session, storage_bytes=storage_bytes)
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
