"""Comparison listing endpoint."""

from __future__ import annotations

from flask import Blueprint, jsonify

from ..extensions import get_database
from .samples import _pagination_args
from .serializers import serialize_comparison
from cheiloscan.db.repositories import ComparisonRepository

comparisons_bp = Blueprint("comparisons", __name__, url_prefix="/api/comparisons")


@comparisons_bp.get("")
def list_comparisons():
    limit, offset = _pagination_args()
    database = get_database()
    with database.session() as session:
        repository = ComparisonRepository(session)
        comparisons, total = repository.list(limit=limit, offset=offset)
        items = [serialize_comparison(comparison) for comparison in comparisons]

    return jsonify(
        {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )
