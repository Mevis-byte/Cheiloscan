"""Reusable image preprocessing functions.

Each function is pure (input array is never modified), takes explicit
parameters with sensible defaults, and raises ``PreprocessingError`` on
invalid input. The pipeline in ``pipeline.py`` composes them; nothing here
is applied automatically to every image.

Colour convention: images are BGR (OpenCV native) unless the name says
otherwise. ``bgr_to_rgb``/``rgb_to_bgr`` exist for interchange with
RGB-native code (e.g. Pillow, matplotlib) and are explicit, never implicit.
"""

from __future__ import annotations

import cv2
import numpy as np


class PreprocessingError(ValueError):
    """Invalid input or parameters for a preprocessing operation."""


def _require_image(image: np.ndarray, *, name: str = "image") -> np.ndarray:
    if image is None or not isinstance(image, np.ndarray) or image.size == 0:
        raise PreprocessingError(f"{name} must be a non-empty numpy array")
    if image.dtype != np.uint8:
        raise PreprocessingError(
            f"{name} must have dtype uint8, got {image.dtype}"
        )
    return image


def _require_odd(value: int, *, name: str, minimum: int = 3) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PreprocessingError(f"{name} must be an integer")
    if value < minimum or value % 2 == 0:
        raise PreprocessingError(
            f"{name} must be an odd integer >= {minimum}, got {value}"
        )
    return value


def _as_gray(image: np.ndarray) -> np.ndarray:
    _require_image(image)
    if image.ndim == 2:
        return image
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    raise PreprocessingError(f"unsupported image shape: {image.shape}")


# --------------------------------------------------------------- colour


def bgr_to_rgb(image: np.ndarray) -> np.ndarray:
    """Convert a 3-channel BGR image to RGB (no-op for grayscale)."""
    _require_image(image)
    if image.ndim == 2:
        return image.copy()
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2RGB)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def rgb_to_bgr(image: np.ndarray) -> np.ndarray:
    """Convert a 3-channel RGB image to BGR (no-op for grayscale)."""
    _require_image(image)
    if image.ndim == 2:
        return image.copy()
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


def to_grayscale(image: np.ndarray) -> np.ndarray:
    """Convert BGR/RGBA to single-channel grayscale; copy if already gray."""
    return _as_gray(image).copy()


# --------------------------------------------------------------- filters


def gaussian_blur(
    image: np.ndarray, kernel_size: int = 5, sigma: float = 0.0
) -> np.ndarray:
    """Gaussian smoothing. ``kernel_size`` must be odd; sigma 0 = auto."""
    _require_image(image)
    kernel = _require_odd(kernel_size, name="kernel_size")
    if sigma < 0:
        raise PreprocessingError(f"sigma must be >= 0, got {sigma}")
    return cv2.GaussianBlur(image, (kernel, kernel), sigma)


def median_blur(image: np.ndarray, kernel_size: int = 5) -> np.ndarray:
    """Median filter (good for salt-and-pepper noise, preserves edges)."""
    _require_image(image)
    kernel = _require_odd(kernel_size, name="kernel_size")
    return cv2.medianBlur(image, kernel)


def bilateral_filter(
    image: np.ndarray,
    diameter: int = 9,
    sigma_color: float = 75.0,
    sigma_space: float = 75.0,
) -> np.ndarray:
    """Edge-preserving bilateral filter."""
    _require_image(image)
    if diameter < 1:
        raise PreprocessingError(f"diameter must be >= 1, got {diameter}")
    if sigma_color <= 0 or sigma_space <= 0:
        raise PreprocessingError("bilateral sigmas must be positive")
    return cv2.bilateralFilter(
        image, diameter, float(sigma_color), float(sigma_space)
    )


# ---------------------------------------------------------- enhancement


def apply_clahe(
    image: np.ndarray,
    clip_limit: float = 2.0,
    tile_grid_size: int = 8,
) -> np.ndarray:
    """Contrast Limited Adaptive Histogram Equalisation on luminance."""
    gray = _as_gray(image)
    if clip_limit <= 0:
        raise PreprocessingError(f"clip_limit must be positive, got {clip_limit}")
    if tile_grid_size < 2:
        raise PreprocessingError(
            f"tile_grid_size must be >= 2, got {tile_grid_size}"
        )
    clahe = cv2.createCLAHE(
        clipLimit=float(clip_limit),
        tileGridSize=(int(tile_grid_size), int(tile_grid_size)),
    )
    return clahe.apply(gray)


def gamma_correction(image: np.ndarray, gamma: float = 1.0) -> np.ndarray:
    """Apply ``output = 255 * (input / 255) ** gamma`` via a lookup table.

    gamma < 1 brightens midtones, gamma > 1 darkens them, 1.0 is identity.
    """
    _require_image(image)
    if gamma <= 0:
        raise PreprocessingError(f"gamma must be positive, got {gamma}")
    if abs(gamma - 1.0) < 1e-9:
        return image.copy()
    table = np.array(
        [((value / 255.0) ** gamma) * 255.0 for value in range(256)],
        dtype=np.float32,
    )
    table = np.clip(table, 0, 255).astype(np.uint8)
    return cv2.LUT(image, table)


def correct_illumination(
    image: np.ndarray, sigma: float | None = None
) -> np.ndarray:
    """Flatten uneven illumination by dividing out an estimated background.

    The background is a heavily blurred copy of the image. ``sigma`` defaults
    to roughly one eighth of the shorter side, which is large enough to
    follow lighting gradients without following groove detail.
    """
    gray = _as_gray(image)
    height, width = gray.shape[:2]
    if sigma is None:
        sigma = max(8.0, min(height, width) / 8.0)
    if sigma <= 0:
        raise PreprocessingError(f"sigma must be positive, got {sigma}")
    background = cv2.GaussianBlur(gray, (0, 0), float(sigma))
    # Guard against division by zero in fully black regions.
    background = np.maximum(background, 1)
    return cv2.divide(gray, background, scale=255)


def normalize_image(
    image: np.ndarray, lower: float = 0.0, upper: float = 255.0
) -> np.ndarray:
    """Min-max stretch the intensity range to ``[lower, upper]``."""
    _require_image(image)
    if not 0 <= lower < upper <= 255:
        raise PreprocessingError(
            f"normalization bounds must satisfy 0 <= lower < upper <= 255, "
            f"got {lower}, {upper}"
        )
    if int(image.max()) == int(image.min()):
        return image.copy()
    return cv2.normalize(
        image, None, alpha=float(lower), beta=float(upper), norm_type=cv2.NORM_MINMAX
    )


def sharpen(image: np.ndarray, amount: float = 0.6) -> np.ndarray:
    """Unsharp masking: ``image + amount * (image - blurred)``."""
    _require_image(image)
    if amount < 0:
        raise PreprocessingError(f"sharpen amount must be >= 0, got {amount}")
    if amount == 0:
        return image.copy()
    blurred = cv2.GaussianBlur(image, (0, 0), 1.0)
    return cv2.addWeighted(image, 1.0 + float(amount), blurred, -float(amount), 0)
