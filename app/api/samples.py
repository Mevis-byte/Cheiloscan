"""Sample listing endpoint."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest

from ..extensions import get_database
from .serializers import serialize_sample
from cheiloscan.db.repositories import SampleRepository

samples_bp = Blueprint("samples", __name__, url_prefix="/api/samples")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _pagination_args() -> tuple[int, int]:
    """Parse and validate ``limit``/``offset`` query parameters."""
    try:
        limit = int(request.args.get("limit", DEFAULT_LIMIT))
        offset = int(request.args.get("offset", 0))
    except ValueError as exc:
        raise BadRequest("limit and offset must be integers") from exc
    if not 1 <= limit <= MAX_LIMIT:
        raise BadRequest(f"limit must be between 1 and {MAX_LIMIT}")
    if offset < 0:
        raise BadRequest("offset must be zero or a positive integer")
    return limit, offset


@samples_bp.get("")
def list_samples():
    limit, offset = _pagination_args()
    include_deleted = request.args.get("include_deleted", "false").lower() in {
        "1",
        "true",
        "yes",
    }

    database = get_database()
    with database.session() as session:
        repository = SampleRepository(session)
        samples, total = repository.list(
            include_deleted=include_deleted, limit=limit, offset=offset
        )
        items = [serialize_sample(sample) for sample in samples]

    return jsonify(
        {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )
