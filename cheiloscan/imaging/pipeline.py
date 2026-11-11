"""Preprocessing pipeline: grayscale -> denoise -> illumination -> contrast -> final.

The pipeline is deliberately conservative. Every enhancement stage can be
disabled, and a disabled stage passes the previous image through unchanged
(marked ``skipped`` in the output) instead of silently doing something else.
Grayscale conversion is the only unconditional step, because groove
enhancement is luminance-based by design.

Parameter validation is strict: unknown keys, wrong types and out-of-range
values are rejected before any processing happens, so a stored run always
has a valid, reproducible parameter snapshot.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Mapping

import numpy as np

from . import preprocess
from .quality import QualityReport, QualityThresholds, assess_quality

PIPELINE_NAME = "preprocess_baseline"
PIPELINE_VERSION = "1"

DENOISE_METHODS = ("none", "gaussian", "median", "bilateral")
OUTPUT_FORMATS = ("png", "jpeg", "webp")

#: Stage roles in execution order. ``grayscale`` is first because every later
#: stage operates on luminance; ``final`` is the image the researcher sees.
ARTIFACT_ROLES = (
    "grayscale",
    "denoised",
    "illumination_corrected",
    "contrast_enhanced",
    "final",
)


class InvalidParameterError(ValueError):
    """Processing parameters are invalid; nothing was executed."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class PreprocessParams:
    """Validated preprocessing parameters (the stored input snapshot)."""

    denoise: str = "bilateral"
    denoise_kernel: int = 5
    bilateral_diameter: int = 9
    bilateral_sigma_color: float = 75.0
    bilateral_sigma_space: float = 75.0
    illumination_correction: bool = True
    illumination_sigma: float | None = None
    clahe: bool = True
    clahe_clip_limit: float = 2.0
    clahe_tile_grid_size: int = 8
    gamma: float = 1.0
    normalize: bool = True
    sharpen: bool = True
    sharpen_amount: float = 0.6
    output_format: str = "png"
    output_quality: int = 95

    # ------------------------------------------------------------------ io

    @classmethod
    def allowed_keys(cls) -> frozenset[str]:
        return frozenset(item.name for item in fields(cls))

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, Any] | None
    ) -> "PreprocessParams":
        """Build params from a JSON mapping, raising on any invalid value."""
        if payload is None:
            return cls()
        if not isinstance(payload, Mapping):
            raise InvalidParameterError(["parameters must be a JSON object"])

        allowed = cls.allowed_keys()
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise InvalidParameterError(
                [f"unknown parameter(s): {', '.join(unknown)}"]
            )

        errors: list[str] = []

        def read(name: str, expected: type, default: Any) -> Any:
            if name not in payload:
                return default
            value = payload[name]
            if expected is bool:
                if not isinstance(value, bool):
                    errors.append(f"{name} must be a boolean")
                    return default
                return value
            if expected is int:
                if isinstance(value, bool) or not isinstance(value, int):
                    errors.append(f"{name} must be an integer")
                    return default
                return value
            if expected is float:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    errors.append(f"{name} must be a number")
                    return default
                return float(value)
            if expected is str:
                if not isinstance(value, str):
                    errors.append(f"{name} must be a string")
                    return default
                return value
            raise AssertionError(f"unsupported type for {name}")

        defaults = cls()
        denoise = read("denoise", str, defaults.denoise).lower()
        if denoise not in DENOISE_METHODS:
            errors.append(
                f"denoise must be one of {sorted(DENOISE_METHODS)}, got {denoise!r}"
            )
        denoise_kernel = read("denoise_kernel", int, defaults.denoise_kernel)
        if denoise_kernel < 3 or denoise_kernel > 31 or denoise_kernel % 2 == 0:
            errors.append("denoise_kernel must be an odd integer between 3 and 31")
        bilateral_diameter = read(
            "bilateral_diameter", int, defaults.bilateral_diameter
        )
        if not 1 <= bilateral_diameter <= 51:
            errors.append("bilateral_diameter must be between 1 and 51")
        sigma_color = read(
            "bilateral_sigma_color", float, defaults.bilateral_sigma_color
        )
        if not 1.0 <= sigma_color <= 255.0:
            errors.append("bilateral_sigma_color must be between 1 and 255")
        sigma_space = read(
            "bilateral_sigma_space", float, defaults.bilateral_sigma_space
        )
        if not 1.0 <= sigma_space <= 255.0:
            errors.append("bilateral_sigma_space must be between 1 and 255")
        illumination_correction = read(
            "illumination_correction", bool, defaults.illumination_correction
        )
        illumination_sigma = payload.get("illumination_sigma", defaults.illumination_sigma)
        if illumination_sigma is not None:
            if isinstance(illumination_sigma, bool) or not isinstance(
                illumination_sigma, (int, float)
            ):
                errors.append("illumination_sigma must be a number or null")
                illumination_sigma = None
            else:
                illumination_sigma = float(illumination_sigma)
                if not 1.0 <= illumination_sigma <= 1000.0:
                    errors.append(
                        "illumination_sigma must be between 1 and 1000"
                    )
        clahe = read("clahe", bool, defaults.clahe)
        clip_limit = read("clahe_clip_limit", float, defaults.clahe_clip_limit)
        if not 0.1 <= clip_limit <= 10.0:
            errors.append("clahe_clip_limit must be between 0.1 and 10")
        tile = read(
            "clahe_tile_grid_size", int, defaults.clahe_tile_grid_size
        )
        if not 2 <= tile <= 32:
            errors.append("clahe_tile_grid_size must be between 2 and 32")
        gamma = read("gamma", float, defaults.gamma)
        if not 0.2 <= gamma <= 5.0:
            errors.append("gamma must be between 0.2 and 5.0")
        normalize = read("normalize", bool, defaults.normalize)
        sharpen = read("sharpen", bool, defaults.sharpen)
        sharpen_amount = read("sharpen_amount", float, defaults.sharpen_amount)
        if not 0.0 <= sharpen_amount <= 3.0:
            errors.append("sharpen_amount must be between 0 and 3")
        output_format = read(
            "output_format", str, defaults.output_format
        ).lower()
        if output_format not in OUTPUT_FORMATS:
            errors.append(
                f"output_format must be one of {sorted(OUTPUT_FORMATS)}"
            )
        output_quality = read("output_quality", int, defaults.output_quality)
        if not 1 <= output_quality <= 100:
            errors.append("output_quality must be between 1 and 100")

        if errors:
            raise InvalidParameterError(errors)

        return cls(
            denoise=denoise,
            denoise_kernel=denoise_kernel,
            bilateral_diameter=bilateral_diameter,
            bilateral_sigma_color=sigma_color,
            bilateral_sigma_space=sigma_space,
            illumination_correction=illumination_correction,
            illumination_sigma=illumination_sigma,
            clahe=clahe,
            clahe_clip_limit=clip_limit,
            clahe_tile_grid_size=tile,
            gamma=gamma,
            normalize=normalize,
            sharpen=sharpen,
            sharpen_amount=sharpen_amount,
            output_format=output_format,
            output_quality=output_quality,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StageResult:
    """One pipeline stage output (a real image array, never a placeholder)."""

    role: str
    image: np.ndarray
    operation: str
    skipped: bool
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineResult:
    """All stage images, measured quality and the executed parameters."""

    stages: tuple[StageResult, ...]
    quality_before: QualityReport
    quality_after: QualityReport
    params: PreprocessParams
    timings_ms: dict[str, float]
    notes: list[str]

    def stage(self, role: str) -> StageResult:
        for stage in self.stages:
            if stage.role == role:
                return stage
        raise KeyError(role)

    @property
    def final_image(self) -> np.ndarray:
        return self.stage("final").image

    def to_summary(self) -> dict[str, Any]:
        """JSON-safe description of the run (no image data)."""
        return {
            "pipeline": {"name": PIPELINE_NAME, "version": PIPELINE_VERSION},
            "params": self.params.to_dict(),
            "stages": [
                {
                    "role": stage.role,
                    "operation": stage.operation,
                    "skipped": stage.skipped,
                    "params": stage.params,
                }
                for stage in self.stages
            ],
            "quality_before": self.quality_before.to_dict(),
            "quality_after": self.quality_after.to_dict(),
            "timings_ms": {
                key: round(value, 3) for key, value in self.timings_ms.items()
            },
            "notes": list(self.notes),
        }


def _denoise(
    gray: np.ndarray, params: PreprocessParams
) -> tuple[np.ndarray, str, bool]:
    if params.denoise == "none":
        return gray.copy(), "none", True
    if params.denoise == "gaussian":
        return (
            preprocess.gaussian_blur(gray, params.denoise_kernel),
            f"gaussian_blur(kernel={params.denoise_kernel})",
            False,
        )
    if params.denoise == "median":
        return (
            preprocess.median_blur(gray, params.denoise_kernel),
            f"median_blur(kernel={params.denoise_kernel})",
            False,
        )
    return (
        preprocess.bilateral_filter(
            gray,
            diameter=params.bilateral_diameter,
            sigma_color=params.bilateral_sigma_color,
            sigma_space=params.bilateral_sigma_space,
        ),
        (
            "bilateral_filter("
            f"d={params.bilateral_diameter},"
            f"sigma_color={params.bilateral_sigma_color},"
            f"sigma_space={params.bilateral_sigma_space})"
        ),
        False,
    )


def run_pipeline(
    original_bgr: np.ndarray,
    params: PreprocessParams | None = None,
    thresholds: QualityThresholds | None = None,
) -> PipelineResult:
    """Execute the preprocessing pipeline on a BGR working copy.

    The input array is never modified. Returns every stage image so the
    caller can persist and preview real outputs.
    """
    if original_bgr is None or original_bgr.size == 0:
        raise preprocess.PreprocessingError("original image is empty")
    params = params or PreprocessParams()
    thresholds = thresholds or QualityThresholds()

    timings: dict[str, float] = {}
    notes: list[str] = []
    stages: list[StageResult] = []
    total_started = time.perf_counter()

    # 1. Grayscale (always applied: enhancement is luminance-based).
    started = time.perf_counter()
    gray = preprocess.to_grayscale(original_bgr)
    timings["grayscale"] = (time.perf_counter() - started) * 1000.0
    stages.append(
        StageResult(
            role="grayscale",
            image=gray,
            operation="to_grayscale",
            skipped=False,
            params={},
        )
    )

    # 2. Denoising.
    started = time.perf_counter()
    denoised, operation, skipped = _denoise(gray, params)
    timings["denoised"] = (time.perf_counter() - started) * 1000.0
    if skipped:
        notes.append("Denoising disabled: stage passed through unchanged.")
    stages.append(
        StageResult(
            role="denoised",
            image=denoised,
            operation=operation,
            skipped=skipped,
            params={
                "method": params.denoise,
                "kernel": params.denoise_kernel,
            },
        )
    )

    # 3. Illumination correction.
    started = time.perf_counter()
    if params.illumination_correction:
        corrected = preprocess.correct_illumination(
            denoised, params.illumination_sigma
        )
        operation = "correct_illumination"
        skipped = False
    else:
        corrected = denoised.copy()
        operation = "none"
        skipped = True
        notes.append(
            "Illumination correction disabled: stage passed through unchanged."
        )
    timings["illumination_corrected"] = (time.perf_counter() - started) * 1000.0
    stages.append(
        StageResult(
            role="illumination_corrected",
            image=corrected,
            operation=operation,
            skipped=skipped,
            params={
                "enabled": params.illumination_correction,
                "sigma": params.illumination_sigma,
            },
        )
    )

    # 4. Contrast enhancement (CLAHE, then optional gamma).
    started = time.perf_counter()
    applied: list[str] = []
    enhanced = corrected
    if params.clahe:
        enhanced = preprocess.apply_clahe(
            enhanced, params.clahe_clip_limit, params.clahe_tile_grid_size
        )
        applied.append(
            "clahe("
            f"clip={params.clahe_clip_limit},"
            f"tiles={params.clahe_tile_grid_size})"
        )
    if abs(params.gamma - 1.0) > 1e-9:
        enhanced = preprocess.gamma_correction(enhanced, params.gamma)
        applied.append(f"gamma({params.gamma})")
    if not applied:
        enhanced = corrected.copy()
        notes.append("Contrast enhancement disabled: stage passed through unchanged.")
    timings["contrast_enhanced"] = (time.perf_counter() - started) * 1000.0
    stages.append(
        StageResult(
            role="contrast_enhanced",
            image=enhanced,
            operation=" + ".join(applied) if applied else "none",
            skipped=not applied,
            params={
                "clahe": params.clahe,
                "clahe_clip_limit": params.clahe_clip_limit,
                "clahe_tile_grid_size": params.clahe_tile_grid_size,
                "gamma": params.gamma,
            },
        )
    )

    # 5. Final: normalization and sharpening.
    started = time.perf_counter()
    final = enhanced
    applied = []
    if params.normalize:
        final = preprocess.normalize_image(final)
        applied.append("normalize_image")
    if params.sharpen:
        final = preprocess.sharpen(final, params.sharpen_amount)
        applied.append(f"sharpen(amount={params.sharpen_amount})")
    if not applied:
        final = enhanced.copy()
        notes.append("Normalization/sharpening disabled: final equals contrast stage.")
    timings["final"] = (time.perf_counter() - started) * 1000.0
    stages.append(
        StageResult(
            role="final",
            image=final,
            operation=" + ".join(applied) if applied else "none",
            skipped=not applied,
            params={
                "normalize": params.normalize,
                "sharpen": params.sharpen,
                "sharpen_amount": params.sharpen_amount,
            },
        )
    )

    quality_before = assess_quality(gray, thresholds)
    quality_after = assess_quality(final, thresholds)
    timings["total"] = (time.perf_counter() - total_started) * 1000.0

    return PipelineResult(
        stages=tuple(stages),
        quality_before=quality_before,
        quality_after=quality_after,
        params=params,
        timings_ms=timings,
        notes=notes,
    )
