"""Processing service: run the pipeline, persist artifacts, record results.

Lifecycle:

1. validate parameters and resolve the input in a short read transaction;
2. end that transaction, then decode/process/encode **outside** any database
   transaction (the CPU-heavy part no longer holds a SQLite write lock);
3. open one short write transaction to create the run, artifacts and results.

The run record is created after processing with its final status:
``succeeded`` with measured results, or ``failed`` with a public error message.
A pipeline failure is recorded on the run rather than raised, so the failure
is visible in the history; only invalid *parameters* abort before a run exists.
The ``running`` status remains part of the schema for a future async worker.

Everything stored is measured. No placeholder scores, no invented metrics.
"""

from __future__ import annotations

import shutil
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db.models import AnalysisRun, new_uuid, utc_now
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
from ..storage.asset_store import AssetStore, StorageError, StoredFile
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

    input_asset = ImageAssetRepository(session).latest_original_for_sample(sample.id)
    if input_asset is None:
        raise NoImageError(
            "this sample has no original image to process",
            details={"sample_id": sample.id},
        )

    # Snapshot only primitives: the session is committed before the expensive
    # work, so ORM instances must not be touched afterwards.
    resolved_sample_id = str(sample.id)
    input_info = {
        "id": str(input_asset.id),
        "storage_path": str(input_asset.storage_path),
        "sha256": str(input_asset.sha256),
        "format": str(input_asset.format),
        "width": int(input_asset.width),
        "height": int(input_asset.height),
    }
    session.commit()  # end the read-only transaction before CPU work

    thresholds = thresholds or QualityThresholds()
    analyses = AnalysisRepository(session)
    assets = ImageAssetRepository(session)
    run_id = new_uuid()
    started_at = utc_now()

    try:
        data = store.read(input_info["storage_path"])
        decoded = decode_image(data)
        result = run_pipeline(decoded.bgr, params, thresholds)
        encoded_stages = _encode_stages(result, params)
        # Store files before opening the write transaction. Derived files are
        # per-run, so a retry can never clobber another run's artifacts.
        stored_stages: list[tuple[str, StoredFile, int, int]] = []
        for role, payload, width, height in encoded_stages:
            stored = store.save_derived(
                payload, run_id=run_id, role=role, image_format=params.output_format
            )
            stored_stages.append((role, stored, width, height))
    except SQLAlchemyError:
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, never swallowed silently
        _remove_derived_run(store, run_id)
        _record_failed_run(
            analyses=analyses,
            run_id=run_id,
            sample_id=resolved_sample_id,
            input_asset_id=input_info["id"],
            params=params,
            thresholds=thresholds,
            started_at=started_at,
            error=_public_error(exc),
            session=session,
        )
        return get_analysis(session, run_id)

    # Short write transaction: no image processing happens from here on.
    run = analyses.create(
        run_id=run_id,
        sample_id=resolved_sample_id,
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
        input_asset_id=input_info["id"],
    )
    run.started_at = started_at
    session.flush()

    _persist_artifacts(
        analyses=analyses,
        assets=assets,
        run=run,
        sample_id=resolved_sample_id,
        input_asset_id=input_info["id"],
        result=result,
        stored_stages=stored_stages,
        output_format=params.output_format,
    )
    run.results = {
        **result.to_summary(),
        "input": {
            "asset_id": input_info["id"],
            "sha256": input_info["sha256"],
            "format": input_info["format"],
            "width": input_info["width"],
            "height": input_info["height"],
        },
        "output": {
            "format": params.output_format,
            "quality": params.output_quality,
        },
    }
    run.status = "succeeded"
    run.finished_at = utc_now()
    session.flush()
    return run


def _record_failed_run(
    *,
    session: Session,
    analyses: AnalysisRepository,
    run_id: str,
    sample_id: str,
    input_asset_id: str,
    params: PreprocessParams,
    thresholds: QualityThresholds,
    started_at: Any,
    error: str,
) -> AnalysisRun:
    run = analyses.create(
        run_id=run_id,
        sample_id=sample_id,
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
        status="failed",
        input_asset_id=input_asset_id,
    )
    run.started_at = started_at
    run.error = error
    run.finished_at = utc_now()
    session.flush()
    return run


def _remove_derived_run(store: AssetStore, run_id: str) -> None:
    """Remove stage files written before a failed run is finalized."""
    try:
        directory = store.resolve(f"derived/{run_id}")
    except StorageError:  # pragma: no cover - generated ids are always safe
        return
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)


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
    analyses: AnalysisRepository,
    assets: ImageAssetRepository,
    run: AnalysisRun,
    sample_id: str,
    input_asset_id: str,
    result: PipelineResult,
    stored_stages: list[tuple[str, StoredFile, int, int]],
    output_format: str,
) -> None:
    by_role = {stage.role: stage for stage in result.stages}
    for role, stored, width, height in stored_stages:
        stage = by_role[role]
        asset = assets.create(
            sample_id=sample_id,
            kind="derived",
            sha256=stored.sha256,
            storage_path=stored.relative_path,
            format=output_format,
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
        analyses.add_artifact(run_id=run.id, image_asset_id=asset.id, role=role)


def _public_error(exc: Exception) -> str:
    """A client-safe failure description (never a filesystem path)."""
    if isinstance(exc, StorageError):
        return "a storage error prevented the pipeline from completing"
    if isinstance(
        exc, (ImageDecodeError, UnsupportedFormatError, PreprocessingError)
    ):
        return str(exc)
    if isinstance(exc, OSError):
        return "the original image could not be read from local storage"
    return f"processing failed ({type(exc).__name__})"
