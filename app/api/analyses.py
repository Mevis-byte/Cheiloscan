"""Analysis endpoints: start a processing run and read its real results."""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.exceptions import BadRequest

from ..extensions import get_asset_store, get_database
from .samples import _pagination_args
from .serializers import serialize_analysis_run, serialize_artifact
from cheiloscan.db.repositories import AnalysisRepository
from cheiloscan.imaging.quality import QualityThresholds
from cheiloscan.services.processing import get_analysis, process_sample

analysis_bp = Blueprint("analysis", __name__)
analyses_bp = Blueprint("analyses", __name__, url_prefix="/api/analyses")


def _quality_thresholds() -> QualityThresholds:
    config = current_app.config
    return QualityThresholds(
        min_width=config["MIN_IMAGE_DIMENSION"],
        min_height=config["MIN_IMAGE_DIMENSION"],
        recommended_min_dimension=config["QUALITY_RECOMMENDED_MIN_DIMENSION"],
        min_blur_variance=config["QUALITY_MIN_BLUR_VARIANCE"],
        min_brightness=config["QUALITY_MIN_BRIGHTNESS"],
        max_brightness=config["QUALITY_MAX_BRIGHTNESS"],
        min_contrast_std=config["QUALITY_MIN_CONTRAST"],
        max_clipped_fraction=config["QUALITY_MAX_CLIPPED_FRACTION"],
    )


def _params_payload() -> dict:
    """Accept either a flat parameter object or ``{"params": {...}}``."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise BadRequest("request body must be valid JSON")
    if not isinstance(payload, dict):
        raise BadRequest("request body must be a JSON object")
    if "params" in payload:
        params = payload["params"]
        if not isinstance(params, dict):
            raise BadRequest("'params' must be a JSON object")
        return params
    return payload


def _analysis_body(run) -> dict:
    return {
        "analysis": serialize_analysis_run(run),
        "artifacts": [serialize_artifact(item) for item in run.artifacts],
    }


@analysis_bp.post("/api/analysis/<sample_id>/process")
def process(sample_id: str):
    """Run the preprocessing pipeline over the sample's newest original."""
    params_payload = _params_payload()
    database = get_database()
    store = get_asset_store()
    with database.session() as session:
        run = process_sample(
            session,
            store,
            sample_id,
            params_payload,
            thresholds=_quality_thresholds(),
        )
        run = get_analysis(session, run.id)
        body = _analysis_body(run)
        succeeded = str(run.status) == "succeeded"
        error = run.error

    if succeeded:
        return jsonify(body), 201

    # The run is persisted as failed (it is history); the request reports the
    # failure with the same envelope shape as other errors.
    return (
        jsonify(
            {
                "error": {
                    "code": "processing_failed",
                    "message": error or "processing failed",
                    "details": {"analysis_id": body["analysis"]["id"]},
                },
                "request_id": g.get("request_id"),
                "analysis": body["analysis"],
                "artifacts": body["artifacts"],
            }
        ),
        500,
    )


@analysis_bp.get("/api/analysis/<analysis_id>")
def read(analysis_id: str):
    """Return one run with its measured results and artifact references."""
    database = get_database()
    with database.session() as session:
        run = get_analysis(session, analysis_id)
        body = _analysis_body(run)
        body["sample"] = {
            "id": run.sample_id,
            "code": run.sample.code if run.sample is not None else None,
        }
    return jsonify(body)


@analyses_bp.get("")
def list_analyses():
    """List runs (newest first) with status filters."""
    limit, offset = _pagination_args()
    sample_id = request.args.get("sample_id")
    status = request.args.get("status")

    database = get_database()
    with database.session() as session:
        runs, total = AnalysisRepository(session).list(
            sample_id=sample_id, status=status, limit=limit, offset=offset
        )
        items = []
        for run in runs:
            item = serialize_analysis_run(run)
            item["sample"] = {
                "id": run.sample_id,
                "code": run.sample.code if run.sample is not None else None,
            }
            item["artifact_count"] = len(run.artifacts)
            items.append(item)

    return jsonify(
        {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )
