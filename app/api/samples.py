"""Sample endpoints: listing and image upload (intake)."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest

from ..extensions import get_asset_store, get_database
from .serializers import serialize_image_asset, serialize_sample
from cheiloscan.db.repositories import SampleRepository
from cheiloscan.imaging.quality import QualityThresholds
from cheiloscan.services.intake import (
    IntakeConfig,
    InvalidSampleMetadataError,
    intake_image,
)

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


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_text(name: str) -> str | None:
    value = request.form.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_captured_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidSampleMetadataError(
            "captured_at must be an ISO-8601 date or timestamp",
            details={"field": "captured_at"},
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _intake_config() -> IntakeConfig:
    config = current_app.config
    thresholds = QualityThresholds(
        min_width=config["MIN_IMAGE_DIMENSION"],
        min_height=config["MIN_IMAGE_DIMENSION"],
        recommended_min_dimension=config["QUALITY_RECOMMENDED_MIN_DIMENSION"],
        min_blur_variance=config["QUALITY_MIN_BLUR_VARIANCE"],
        min_brightness=config["QUALITY_MIN_BRIGHTNESS"],
        max_brightness=config["QUALITY_MAX_BRIGHTNESS"],
        min_contrast_std=config["QUALITY_MIN_CONTRAST"],
        max_clipped_fraction=config["QUALITY_MAX_CLIPPED_FRACTION"],
    )
    return IntakeConfig(
        max_upload_bytes=int(config["MAX_CONTENT_LENGTH"]),
        min_dimension=int(config["MIN_IMAGE_DIMENSION"]),
        max_dimension=int(config["MAX_IMAGE_DIMENSION"]),
        thresholds=thresholds,
    )


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


@samples_bp.post("/upload")
def upload_sample():
    """Upload one image, create its sample, store the immutable original."""
    if "file" not in request.files:
        raise BadRequest("multipart field 'file' is required")
    upload = request.files["file"]
    data = upload.read()
    if not data:
        raise BadRequest("multipart field 'file' is empty")

    database = get_database()
    store = get_asset_store()
    with database.session() as session:
        result = intake_image(
            session,
            store,
            data,
            filename=upload.filename,
            code=_optional_text("code"),
            research_notes=_optional_text("research_notes"),
            capture_type=_optional_text("capture_type"),
            medium=_optional_text("medium"),
            collection_method=_optional_text("collection_method"),
            donor_ref=_optional_text("donor_ref"),
            consent_confirmed=_truthy(request.form.get("consent_confirmed")),
            captured_at=_parse_captured_at(request.form.get("captured_at")),
            config=_intake_config(),
        )
        body = {
            "sample": serialize_sample(result.sample),
            "asset": serialize_image_asset(result.asset),
            "quality": result.quality.to_dict(),
            "warnings": result.quality.warnings,
        }
    return jsonify(body), 201
