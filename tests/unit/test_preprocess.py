"""Unit tests: reusable preprocessing functions."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from cheiloscan.imaging import preprocess
from tests import fixtures_gen


def test_to_grayscale_converts_bgr_and_copies_gray():
    colour = fixtures_gen.sharp_texture()
    gray = preprocess.to_grayscale(colour)
    assert gray.ndim == 2
    assert gray.shape == colour.shape[:2]
    # A grayscale input is copied, never aliased.
    again = preprocess.to_grayscale(gray)
    assert again is not gray
    assert np.array_equal(again, gray)


def test_bgr_rgb_roundtrip():
    image = fixtures_gen.mid_gray(32, 24)
    rgb = preprocess.bgr_to_rgb(image)
    back = preprocess.rgb_to_bgr(rgb)
    assert np.array_equal(back, image)


def test_gaussian_blur_reduces_variance_without_mutating_input():
    image = fixtures_gen.sharp_texture()
    original = image.copy()
    blurred = preprocess.gaussian_blur(image, 7)
    assert np.array_equal(image, original)
    assert cv2.Laplacian(cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() < (
        cv2.Laplacian(cv2.cvtColor(original, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
    )


def test_median_and_bilateral_preserve_shape_and_dtype():
    image = fixtures_gen.sharp_texture(96, 96)
    for filtered in (
        preprocess.median_blur(image, 5),
        preprocess.bilateral_filter(image, 5),
    ):
        assert filtered.shape == image.shape
        assert filtered.dtype == np.uint8


def test_gamma_identity_is_a_copy_and_lower_gamma_brightens():
    image = fixtures_gen.mid_gray(64, 64, value=100)
    identity = preprocess.gamma_correction(image, 1.0)
    assert identity is not image
    assert np.array_equal(identity, image)

    brightened = preprocess.gamma_correction(image, 0.5)
    assert float(brightened.mean()) > float(image.mean())
    darkened = preprocess.gamma_correction(image, 2.0)
    assert float(darkened.mean()) < float(image.mean())


def test_clahe_accepts_colour_and_returns_luminance():
    image = fixtures_gen.low_contrast()
    enhanced = preprocess.apply_clahe(image)
    assert enhanced.ndim == 2
    assert float(enhanced.std()) > float(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).std())


def test_illumination_correction_flattens_a_gradient():
    image = fixtures_gen.gradient()
    corrected = preprocess.correct_illumination(image)
    assert corrected.ndim == 2
    # Compare central quarters: the outer border is affected by the blurred
    # background estimate at the image edge.
    width = corrected.shape[1]
    left = float(corrected[:, width // 4 : width // 4 + width // 8].mean())
    right = float(corrected[:, -width // 4 - width // 8 : -width // 4].mean())
    assert abs(left - right) < 20.0


def test_normalize_stretches_range_and_handles_constant_image():
    image = fixtures_gen.low_contrast()
    normalized = preprocess.normalize_image(image)
    assert int(normalized.min()) == 0
    assert int(normalized.max()) == 255

    constant = np.full((8, 8), 77, dtype=np.uint8)
    assert np.array_equal(preprocess.normalize_image(constant), constant)


def test_sharpen_zero_is_copy_and_positive_increases_edge_energy():
    image = fixtures_gen.blurry(96, 96)
    assert np.array_equal(preprocess.sharpen(image, 0.0), image)
    sharpened = preprocess.sharpen(image, 1.0)
    assert sharpened.dtype == np.uint8
    assert float(sharpened.std()) >= float(image.std())


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda: preprocess.gaussian_blur(np.zeros((8, 8), np.uint8), 4), "odd"),
        (lambda: preprocess.gaussian_blur(np.zeros((8, 8), np.uint8), 1), "odd"),
        (lambda: preprocess.median_blur(np.zeros((8, 8), np.uint8), 2), "odd"),
        (lambda: preprocess.bilateral_filter(np.zeros((8, 8), np.uint8), 0), "diameter"),
        (
            lambda: preprocess.bilateral_filter(
                np.zeros((8, 8), np.uint8), 5, sigma_color=0
            ),
            "positive",
        ),
        (lambda: preprocess.apply_clahe(np.zeros((8, 8), np.uint8), clip_limit=0), "positive"),
        (lambda: preprocess.apply_clahe(np.zeros((8, 8), np.uint8), tile_grid_size=1), "tile"),
        (lambda: preprocess.gamma_correction(np.zeros((8, 8), np.uint8), 0), "positive"),
        (
            lambda: preprocess.correct_illumination(np.zeros((8, 8), np.uint8), 0),
            "positive",
        ),
        (
            lambda: preprocess.normalize_image(np.zeros((8, 8), np.uint8), 10, 5),
            "bounds",
        ),
        (lambda: preprocess.sharpen(np.zeros((8, 8), np.uint8), -1), "amount"),
    ],
)
def test_invalid_parameters_raise_preprocessing_error(call, match):
    with pytest.raises(preprocess.PreprocessingError, match=match):
        call()


def test_invalid_image_inputs_are_rejected():
    with pytest.raises(preprocess.PreprocessingError, match="non-empty"):
        preprocess.to_grayscale(np.array([], dtype=np.uint8))
    with pytest.raises(preprocess.PreprocessingError, match="dtype uint8"):
        preprocess.gaussian_blur(np.zeros((8, 8), np.float32), 3)
    with pytest.raises(preprocess.PreprocessingError, match="shape"):
        preprocess.to_grayscale(np.zeros((8, 8, 5), np.uint8))
