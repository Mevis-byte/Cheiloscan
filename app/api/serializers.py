"""API response serializers.

Deliberate information policy:

- internal storage paths are never serialized (``storage_path`` must not
  appear in any API payload - guarded by tests);
- timestamps are rendered as UTC ISO-8601 strings ending in ``Z``;
- enum values are rendered as their plain string values.
"""

from __future__ import annotations

from datetime import datetime

from cheiloscan.db.models import AnalysisRun, Comparison, ImageAsset, Sample


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def serialize_image_asset(asset: ImageAsset) -> dict:
    meta = asset.capture_meta or {}
    return {
        "id": asset.id,
        "sample_id": asset.sample_id,
        "kind": str(asset.kind),
        "sha256": asset.sha256,
        "format": asset.format,
        "width": asset.width,
        "height": asset.height,
        "size_bytes": asset.size_bytes,
        "parent_asset_id": asset.parent_asset_id,
        "created_at": _iso_utc(asset.created_at),
        # Provenance/measurement summaries only; internal paths are excluded.
        "original_filename": meta.get("original_filename"),
        "quality": meta.get("quality"),
        "role": meta.get("role"),
        "file_url": f"/api/assets/{asset.id}/file",
    }


def serialize_sample(sample: Sample) -> dict:
    return {
        "id": sample.id,
        "code": sample.code,
        "research_notes": sample.research_notes,
        "capture_type": str(sample.capture_type) if sample.capture_type else None,
        "medium": sample.medium,
        "collection_method": sample.collection_method,
        "donor_ref": sample.donor_ref,
        "consent_confirmed": sample.consent_confirmed,
        "captured_at": _iso_utc(sample.captured_at),
        "created_at": _iso_utc(sample.created_at),
        "updated_at": _iso_utc(sample.updated_at),
        "deleted_at": _iso_utc(sample.deleted_at),
        "image_count": len(sample.images),
        "analyses_count": len(sample.analyses),
        "images": [serialize_image_asset(asset) for asset in sample.images],
    }


def serialize_comparison(comparison: Comparison) -> dict:
    def _sample_ref(sample) -> dict | None:
        if sample is None:
            return None
        return {"id": sample.id, "code": sample.code}

    return {
        "id": comparison.id,
        "method": comparison.method,
        "method_version": comparison.method_version,
        "status": str(comparison.status),
        "params": comparison.params,
        "component_scores": comparison.component_scores,
        "fused_score": comparison.fused_score,
        "error": comparison.error,
        "created_at": _iso_utc(comparison.created_at),
        "finished_at": _iso_utc(comparison.finished_at),
        "sample_a": _sample_ref(comparison.sample_a),
        "sample_b": _sample_ref(comparison.sample_b),
    }


def serialize_analysis_run(run: AnalysisRun) -> dict:
    return {
        "id": run.id,
        "sample_id": run.sample_id,
        "input_asset_id": run.input_asset_id,
        "pipeline_name": run.pipeline_name,
        "pipeline_version": run.pipeline_version,
        "status": str(run.status),
        "params": run.params,
        "results": run.results,
        "error": run.error,
        "created_at": _iso_utc(run.created_at),
        "started_at": _iso_utc(run.started_at),
        "finished_at": _iso_utc(run.finished_at),
    }


def serialize_artifact(artifact) -> dict:
    asset = artifact.asset
    return {
        "role": artifact.role,
        "asset_id": artifact.image_asset_id,
        "file_url": f"/api/assets/{artifact.image_asset_id}/file",
        "format": asset.format if asset is not None else None,
        "width": asset.width if asset is not None else None,
        "height": asset.height if asset is not None else None,
        "size_bytes": asset.size_bytes if asset is not None else None,
        "sha256": asset.sha256 if asset is not None else None,
    }
