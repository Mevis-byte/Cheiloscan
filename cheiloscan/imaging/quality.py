"""Image quality measurement and experimental threshold checks.

These measurements are **descriptive**, not diagnostic: they tell the
researcher whether an image is likely to make groove detail hard to see.
They never reject an image on their own and they make no claim about
whether a lip print is identifiable (see docs/SCIENTIFIC_METHODOLOGY.md §2).

Blur is estimated with the variance of the Laplacian::

    score = var(cv2.Laplacian(gray, cv2.CV_64F))

Sharp, high-frequency detail produces a large variance; defocus produces a
small one. The score depends on content, resolution and noise, so the
threshold is deliberately exposed as an experimental configuration value
rather than treated as a universal constant.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

#: Pixels at or below this value count as clipped shadows.
_SHADOW_CLIP_LEVEL = 2
#: Pixels at or above this value count as clipped highlights.
_HIGHLIGHT_CLIP_LEVEL = 253


@dataclass(frozen=True)
class QualityThresholds:
    """Experimental thresholds. All values are configurable per deployment."""

    min_width: int = 128
    min_height: int = 128
    recommended_min_dimension: int = 400
    min_blur_variance: float = 60.0
    min_brightness: float = 40.0
    max_brightness: float = 215.0
    min_contrast_std: float = 25.0
    max_clipped_fraction: float = 0.02

    def __post_init__(self) -> None:
        if self.min_width <= 0 or self.min_height <= 0:
            raise ValueError("minimum dimensions must be positive")
        if self.min_brightness >= self.max_brightness:
            raise ValueError("min_brightness must be below max_brightness")
        if not 0.0 <= self.max_clipped_fraction <= 1.0:
            raise ValueError("max_clipped_fraction must be in [0, 1]")


@dataclass(frozen=True)
class QualityReport:
    """Measured values plus non-blocking warnings."""

    width: int
    height: int
    blur_laplacian_variance: float
    brightness_mean: float
    contrast_std: float
    clipped_low_fraction: float
    clipped_high_fraction: float
    warnings: list[dict[str, object]] = field(default_factory=list)

    @property
    def megapixels(self) -> float:
        return round((self.width * self.height) / 1_000_000.0, 4)

    @property
    def min_dimension(self) -> int:
        return min(self.width, self.height)

    @property
    def is_suitable(self) -> bool:
        """True when no warnings were raised (still not a guarantee)."""
        return not self.warnings

    def to_dict(self) -> dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            "megapixels": self.megapixels,
            "min_dimension": self.min_dimension,
            "blur": {
                "laplacian_variance": round(self.blur_laplacian_variance, 3)
            },
            "brightness": {"mean": round(self.brightness_mean, 3)},
            "contrast": {"std": round(self.contrast_std, 3)},
            "exposure": {
                "clipped_low_fraction": round(self.clipped_low_fraction, 5),
                "clipped_high_fraction": round(self.clipped_high_fraction, 5),
                "clipped_fraction": round(
                    self.clipped_low_fraction + self.clipped_high_fraction, 5
                ),
            },
            "warnings": list(self.warnings),
        }


def _as_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    raise ValueError(f"unsupported image shape for quality assessment: {image.shape}")


def _warning(
    code: str, message: str, measured: float, threshold: float, unit: str
) -> dict[str, object]:
    return {
        "code": code,
        "severity": "warning",
        "message": message,
        "measured": round(float(measured), 3),
        "threshold": round(float(threshold), 3),
        "unit": unit,
    }


def assess_quality(
    image: np.ndarray, thresholds: QualityThresholds | None = None
) -> QualityReport:
    """Measure blur, brightness, contrast, resolution and exposure."""
    if image is None or image.size == 0:
        raise ValueError("cannot assess quality of an empty image")
    thresholds = thresholds or QualityThresholds()
    gray = _as_gray(image)
    height, width = gray.shape[:2]

    blur_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    contrast = float(gray.std())
    total = float(gray.size)
    clipped_low = float(np.count_nonzero(gray <= _SHADOW_CLIP_LEVEL)) / total
    clipped_high = float(np.count_nonzero(gray >= _HIGHLIGHT_CLIP_LEVEL)) / total
    clipped = clipped_low + clipped_high

    warnings: list[dict[str, object]] = []
    if blur_variance < thresholds.min_blur_variance:
        warnings.append(
            _warning(
                "blurry",
                "Low Laplacian variance: the image may be out of focus. "
                "Retake if possible; processing can still be attempted.",
                blur_variance,
                thresholds.min_blur_variance,
                "variance",
            )
        )
    if brightness < thresholds.min_brightness:
        warnings.append(
            _warning(
                "too_dark",
                "Mean brightness is low: grooves may be lost in shadow.",
                brightness,
                thresholds.min_brightness,
                "0-255",
            )
        )
    if brightness > thresholds.max_brightness:
        warnings.append(
            _warning(
                "too_bright",
                "Mean brightness is high: grooves may be washed out.",
                brightness,
                thresholds.max_brightness,
                "0-255",
            )
        )
    if contrast < thresholds.min_contrast_std:
        warnings.append(
            _warning(
                "low_contrast",
                "Low intensity spread: groove boundaries may be indistinct.",
                contrast,
                thresholds.min_contrast_std,
                "std",
            )
        )
    if clipped > thresholds.max_clipped_fraction:
        warnings.append(
            _warning(
                "clipped_exposure",
                "A large fraction of pixels is clipped at pure black or white.",
                clipped,
                thresholds.max_clipped_fraction,
                "fraction",
            )
        )
    if min(width, height) < thresholds.recommended_min_dimension:
        warnings.append(
            _warning(
                "low_resolution",
                "Below the recommended minimum dimension; fine groove detail "
                "may be undersampled.",
                min(width, height),
                thresholds.recommended_min_dimension,
                "px",
            )
        )

    return QualityReport(
        width=width,
        height=height,
        blur_laplacian_variance=blur_variance,
        brightness_mean=brightness,
        contrast_std=contrast,
        clipped_low_fraction=clipped_low,
        clipped_high_fraction=clipped_high,
        warnings=warnings,
    )
