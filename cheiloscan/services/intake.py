"""Image intake: validation, immutable storage, metadata and quality.

Intake is the only path that creates a ``Sample`` and an original
``ImageAsset``. It enforces, in order:

1. non-empty payload and the configured maximum size;
2. supported format by magic bytes (JPEG/PNG/WebP);
3. successful decode (corrupt/truncated files are rejected);
4. absolute dimension floor/ceiling;
5. sample-code uniqueness (explicit code) or auto-generated code;
6. content-hash deduplication of originals (409-style conflict).

Quality problems (blur, exposure, contrast, low resolution) are **not**
rejections: they are measured, stored in ``capture_meta`` and returned as
warnings so the researcher can decide. Only unusable content is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ..db.models import ImageAsset, Sample, utc_now
from ..db.repositories import ImageAssetRepository, SampleRepository
from ..imaging.quality import QualityReport, QualityThresholds, assess_quality
from ..storage.asset_store import AssetStore
from ..util.imageio import (
    DecodedImage,
    ImageDecodeError,
    UnsupportedFormatError,
    decode_image,
    sanitize_filename,
)

#: Allowed ``Sample.capture_type`` values (mirrors the model enum).
CAPTURE_TYPES = ("print_document", "photograph")

MAX_SAMPLE_CODE_LENGTH = 120
_AUTO_CODE_ATTEMPTS = 10


class IntakeError(ValueError):
    """Base class for intake failures with a stable machine-readable code."""

    code = "intake_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)


class UploadTooLargeError(IntakeError):
    code = "file_too_large"


class UnsupportedImageError(IntakeError):
    code = "unsupported_format"


class CorruptImageError(IntakeError):
    code = "invalid_image"


class ImageDimensionsError(IntakeError):
    code = "image_dimensions_invalid"


class DuplicateImageError(IntakeError):
    code = "duplicate_image"


class InvalidSampleMetadataError(IntakeError):
    code = "invalid_sample_metadata"


class SampleCodeConflictError(IntakeError):
    code = "sample_code_conflict"


@dataclass(frozen=True)
class IntakeConfig:
    """Limits applied to one upload (built from the application config)."""

    max_upload_bytes: int = 25 * 1024 * 1024
    min_dimension: int = 128
    max_dimension: int = 12000
    thresholds: QualityThresholds = field(default_factory=QualityThresholds)


@dataclass(frozen=True)
class IntakeResult:
    """Everything produced by a successful intake."""

    sample: Sample
    asset: ImageAsset
    quality: QualityReport
    decoded: DecodedImage


def generate_sample_code() -> str:
    """Auto-generate a unique-looking sample identifier (``S-XXXXXXXX``)."""
    return f"S-{uuid4().hex[:8].upper()}"


def intake_image(
    session: Session,
    store: AssetStore,
    data: bytes,
    *,
    filename: str | None = None,
    code: str | None = None,
    research_notes: str | None = None,
    capture_type: str | None = None,
    medium: str | None = None,
    collection_method: str | None = None,
    donor_ref: str | None = None,
    consent_confirmed: bool = False,
    captured_at: datetime | None = None,
    config: IntakeConfig | None = None,
) -> IntakeResult:
    """Validate and store one uploaded image; create its sample record."""
    config = config or IntakeConfig()

    # 1. Payload size.
    if not data:
        raise CorruptImageError("the uploaded file is empty")
    if len(data) > config.max_upload_bytes:
        raise UploadTooLargeError(
            "the uploaded file exceeds the maximum allowed size",
            details={
                "max_bytes": config.max_upload_bytes,
                "received_bytes": len(data),
            },
        )

    # 2. Format + 3. decode (magic bytes, then real decoding).
    try:
        decoded = decode_image(data)
    except UnsupportedFormatError as exc:
        raise UnsupportedImageError(str(exc)) from exc
    except ImageDecodeError as exc:
        raise CorruptImageError(str(exc)) from exc

    # 4. Dimensions.
    shortest = min(decoded.width, decoded.height)
    longest = max(decoded.width, decoded.height)
    if shortest < config.min_dimension:
        raise ImageDimensionsError(
            "the image is too small for reliable processing",
            details={
                "width": decoded.width,
                "height": decoded.height,
                "min_dimension": config.min_dimension,
            },
        )
    if longest > config.max_dimension:
        raise ImageDimensionsError(
            "the image exceeds the maximum supported dimensions",
            details={
                "width": decoded.width,
                "height": decoded.height,
                "max_dimension": config.max_dimension,
            },
        )

    # 5. Sample metadata.
    if capture_type is not None and capture_type not in CAPTURE_TYPES:
        raise InvalidSampleMetadataError(
            f"capture_type must be one of {sorted(CAPTURE_TYPES)}",
            details={"field": "capture_type"},
        )
    if research_notes is not None and len(research_notes) > 10_000:
        raise InvalidSampleMetadataError(
            "research_notes is too long", details={"field": "research_notes"}
        )

    samples = SampleRepository(session)
    assets = ImageAssetRepository(session)

    if code is not None:
        code = code.strip()
        if not code:
            raise InvalidSampleMetadataError(
                "sample code must not be empty", details={"field": "code"}
            )
        if len(code) > MAX_SAMPLE_CODE_LENGTH:
            raise InvalidSampleMetadataError(
                f"sample code must be at most {MAX_SAMPLE_CODE_LENGTH} characters",
                details={"field": "code"},
            )
        if samples.get_by_code(code) is not None:
            raise SampleCodeConflictError(
                f"a sample with code {code!r} already exists",
                details={"code": code},
            )
    else:
        code = _unique_sample_code(samples)

    # 6. Duplicate originals: one original row per content hash.
    existing = assets.find_original_by_sha256(decoded.sha256)
    if existing is not None:
        raise DuplicateImageError(
            "this image has already been uploaded",
            details={
                "existing_asset_id": existing.id,
                "existing_sample_id": existing.sample_id,
                "existing_sample_code": (
                    existing.sample.code if existing.sample is not None else None
                ),
            },
        )

    quality = assess_quality(decoded.bgr, config.thresholds)
    stored = store.save_original(data, decoded.format)

    sample = samples.create(
        code=code,
        research_notes=research_notes,
        capture_type=capture_type,
        medium=medium,
        collection_method=collection_method,
        donor_ref=donor_ref,
        consent_confirmed=consent_confirmed,
        captured_at=captured_at,
    )

    capture_meta = {
        "source": "upload",
        "original_filename": sanitize_filename(filename),
        "uploaded_at": utc_now().isoformat() + "Z",
        "exif": decoded.exif,
        "exif_orientation": decoded.orientation,
        "quality": quality.to_dict(),
        "intake": {
            "min_dimension": config.min_dimension,
            "max_dimension": config.max_dimension,
            "quality_thresholds": {
                "recommended_min_dimension": config.thresholds.recommended_min_dimension,
                "min_blur_variance": config.thresholds.min_blur_variance,
                "min_brightness": config.thresholds.min_brightness,
                "max_brightness": config.thresholds.max_brightness,
                "min_contrast_std": config.thresholds.min_contrast_std,
                "max_clipped_fraction": config.thresholds.max_clipped_fraction,
            },
        },
    }

    asset = assets.create(
        sample_id=sample.id,
        kind="original",
        sha256=stored.sha256,
        storage_path=stored.relative_path,
        format=decoded.format,
        width=decoded.width,
        height=decoded.height,
        size_bytes=stored.size_bytes,
        capture_meta=capture_meta,
    )

    return IntakeResult(
        sample=sample, asset=asset, quality=quality, decoded=decoded
    )


def _unique_sample_code(samples: SampleRepository) -> str:
    for _ in range(_AUTO_CODE_ATTEMPTS):
        candidate = generate_sample_code()
        if samples.get_by_code(candidate) is None:
            return candidate
    raise IntakeError(  # pragma: no cover - astronomically unlikely
        "could not generate a unique sample code; supply one explicitly"
    )
