"""Processing service: run the pipeline, persist artifacts, record results.

Lifecycle: a run is created as ``running`` (with the full parameter snapshot)
and ends as either ``succeeded`` with measured results and one derived asset
per stage, or ``failed`` with a public error message. A pipeline failure is
recorded on the run rather than raised, so the failure is visible in the
history; only invalid *parameters* abort before a run exists.

Everything stored is measured. No placeholder scores, no invented metrics.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db.models import AnalysisRun, utc_now
from ..db.repositories import (
    AnalysisRepository,
    ImageAssetRepository,
    SampleRepository,
)
from ..imaging.pipeline import (
    PIPELINE_NAME,
    PIPELINE_VERSION,
    PipelineResult,
    PreprocessParams,
    run_pipeline,
)
from ..imaging.quality import QualityThresholds
from ..imaging.preprocess import PreprocessingError
from ..storage.asset_store import AssetStore, StorageError
from ..util.imageio import (
    ImageDecodeError,
    UnsupportedFormatError,
    decode_image,
    encode_image,
)


class ProcessingError(ValueError):
    """Base class for processing request failures."""

    code = "processing_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)


class SampleNotFoundError(ProcessingError):
    code = "sample_not_found"


class NoImageError(ProcessingError):
    code = "sample_has_no_image"


class AnalysisNotFoundError(ProcessingError):
    code = "analysis_not_found"


def get_analysis(session: Session, analysis_id: str) -> AnalysisRun:
    """Return a run with its artifacts, or raise ``AnalysisNotFoundError``."""
    run = AnalysisRepository(session).get_with_artifacts(analysis_id)
    if run is None:
        raise AnalysisNotFoundError(f"analysis run {analysis_id!r} does not exist")
    return run


def process_sample(
    session: Session,
    store: AssetStore,
    sample_id: str,
    params_payload: dict[str, Any] | None = None,
    *,
    thresholds: QualityThresholds | None = None,
) -> AnalysisRun:
    """Process the newest original image of a sample.

    ``params_payload`` is validated **before** any run is created; invalid
    parameters raise ``InvalidParameterError`` (mapped to HTTP 400).
    """
    # Validation first: an invalid request must not leave a run behind.
    params = PreprocessParams.from_mapping(params_payload)

    sample = SampleRepository(session).get(sample_id)
    if sample is None or sample.deleted_at is not None:
        raise SampleNotFoundError(f"sample {sample_id!r} does not exist")

    assets = ImageAssetRepository(session)
    input_asset = assets.latest_original_for_sample(sample.id)
    if input_asset is None:
        raise NoImageError(
            "this sample has no original image to process",
            details={"sample_id": sample.id},
        )

    thresholds = thresholds or QualityThresholds()
    analyses = AnalysisRepository(session)
    run = analyses.create(
        sample_id=sample.id,
        pipeline_name=PIPELINE_NAME,
        pipeline_version=PIPELINE_VERSION,
        params={
            **params.to_dict(),
            "quality_thresholds": {
                "recommended_min_dimension": thresholds.recommended_min_dimension,
                "min_blur_variance": thresholds.min_blur_variance,
                "min_brightness": thresholds.min_brightness,
                "max_brightness": thresholds.max_brightness,
                "min_contrast_std": thresholds.min_contrast_std,
                "max_clipped_fraction": thresholds.max_clipped_fraction,
            },
        },
        status="running",
        input_asset_id=input_asset.id,
    )
    run.started_at = utc_now()
    session.flush()

    try:
        data = store.read(input_asset.storage_path)
        decoded = decode_image(data)
        result = run_pipeline(decoded.bgr, params, thresholds)
        encoded_stages = _encode_stages(result, params)
        # Persist artifacts in a savepoint: if storage or a later step fails,
        # partial artifact rows are rolled back while the failed run itself
        # remains in the outer transaction as history.
        with session.begin_nested():
            _persist_artifacts(
                store=store,
                analyses=analyses,
                assets=assets,
                run=run,
                sample_id=sample.id,
                input_asset_id=input_asset.id,
                result=result,
                encoded_stages=encoded_stages,
                params=params,
            )
        run.results = {
            **result.to_summary(),
            "input": {
                "asset_id": input_asset.id,
                "sha256": input_asset.sha256,
                "format": input_asset.format,
                "width": input_asset.width,
                "height": input_asset.height,
            },
            "output": {
                "format": params.output_format,
                "quality": params.output_quality,
            },
        }
        run.status = "succeeded"
        run.finished_at = utc_now()
        session.flush()
    except SQLAlchemyError:
        # Database failures propagate so the request transaction rolls back;
        # the route's centralized handler reports a generic database error.
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, never swallowed silently
        # Drop any relationship state loaded before the savepoint rollback so
        # a failed run never appears to own partial artifacts.
        try:
            session.expire(run, ["artifacts"])
        except Exception:  # pragma: no cover - run already transient/expired
            pass
        run.status = "failed"
        run.error = _public_error(exc)
        run.finished_at = utc_now()
        session.flush()

    return run


def _encode_stages(
    result: PipelineResult, params: PreprocessParams
) -> list[tuple[str, bytes, int, int]]:
    """Encode every stage in memory before touching the store."""
    encoded: list[tuple[str, bytes, int, int]] = []
    for stage in result.stages:
        payload = encode_image(
            stage.image, params.output_format, quality=params.output_quality
        )
        height, width = stage.image.shape[:2]
        encoded.append((stage.role, payload, int(width), int(height)))
    return encoded


def _persist_artifacts(
    *,
    store: AssetStore,
    analyses: AnalysisRepository,
    assets: ImageAssetRepository,
    run: AnalysisRun,
    sample_id: str,
    input_asset_id: str,
    result: PipelineResult,
    encoded_stages: list[tuple[str, bytes, int, int]],
    params: PreprocessParams,
) -> None:
    by_role = {stage.role: stage for stage in result.stages}
    for role, payload, width, height in encoded_stages:
        stored = store.save_derived(
            payload,
            run_id=run.id,
            role=role,
            image_format=params.output_format,
        )
        stage = by_role[role]
        asset = assets.create(
            sample_id=sample_id,
            kind="derived",
            sha256=stored.sha256,
            storage_path=stored.relative_path,
            format=params.output_format,
            width=width,
            height=height,
            size_bytes=stored.size_bytes,
            parent_asset_id=input_asset_id,
            capture_meta={
                "source": "pipeline",
                "analysis_run_id": run.id,
                "role": role,
                "operation": stage.operation,
                "skipped": stage.skipped,
                "params": stage.params,
            },
        )
        analyses.add_artifact(
            run_id=run.id, image_asset_id=asset.id, role=role
        )


def _public_error(exc: Exception) -> str:
    """A client-safe failure description (never a filesystem path)."""
    if isinstance(
        exc,
        (ImageDecodeError, UnsupportedFormatError, PreprocessingError, StorageError),
    ):
        return str(exc)
    if isinstance(exc, OSError):
        return "the original image could not be read from local storage"
    return f"processing failed ({type(exc).__name__})"
