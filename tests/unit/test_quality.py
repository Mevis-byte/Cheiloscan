"""Unit tests: descriptive image quality measurement."""

from __future__ import annotations

import numpy as np
import pytest

from cheiloscan.imaging.quality import (
    QualityThresholds,
    assess_quality,
)
from tests import fixtures_gen


def _codes(report) -> set[str]:
    return {warning["code"] for warning in report.warnings}


def test_clean_image_has_no_warnings():
    report = assess_quality(fixtures_gen.clean_texture())
    assert report.warnings == []
    assert report.is_suitable is True
    assert report.min_dimension == 512
    assert report.megapixels == pytest.approx(0.2621, abs=1e-4)


def test_blurry_image_is_flagged_but_not_rejected():
    sharp = assess_quality(fixtures_gen.sharp_texture())
    blurred = assess_quality(fixtures_gen.blurry())
    assert blurred.blur_laplacian_variance < sharp.blur_laplacian_variance
    assert "blurry" in _codes(blurred)
    # A warning is descriptive only; the report is still returned in full.
    assert blurred.width == 512 and blurred.height == 384


def test_low_contrast_is_flagged():
    report = assess_quality(fixtures_gen.low_contrast())
    assert "low_contrast" in _codes(report)
    assert report.contrast_std < QualityThresholds().min_contrast_std


def test_underexposed_image_is_flagged():
    report = assess_quality(fixtures_gen.dark())
    assert "too_dark" in _codes(report)
    assert report.brightness_mean < QualityThresholds().min_brightness


def test_overexposed_image_is_flagged():
    report = assess_quality(fixtures_gen.bright())
    assert "too_bright" in _codes(report)
    assert report.brightness_mean > QualityThresholds().max_brightness


def test_clipped_exposure_is_flagged():
    report = assess_quality(fixtures_gen.clipped())
    assert "clipped_exposure" in _codes(report)
    assert report.clipped_low_fraction > 0.4
    assert report.clipped_high_fraction > 0.4


def test_low_resolution_is_flagged_against_recommended_size():
    report = assess_quality(fixtures_gen.mid_gray(200, 200))
    assert "low_resolution" in _codes(report)


def test_thresholds_are_configurable():
    image = fixtures_gen.clean_texture()
    strict = QualityThresholds(min_blur_variance=1_000_000.0)
    assert "blurry" in _codes(assess_quality(image, strict))

    lax = QualityThresholds(
        recommended_min_dimension=64,
        min_blur_variance=0.0,
        min_brightness=0.0,
        max_brightness=255.0,
        min_contrast_std=0.0,
        max_clipped_fraction=1.0,
    )
    assert assess_quality(fixtures_gen.dark(), lax).warnings == []


def test_warning_entries_carry_measured_values_and_thresholds():
    report = assess_quality(fixtures_gen.dark())
    warning = next(w for w in report.warnings if w["code"] == "too_dark")
    assert warning["severity"] == "warning"
    assert warning["measured"] < warning["threshold"]
    assert warning["unit"] == "0-255"
    assert isinstance(warning["message"], str) and warning["message"]


def test_to_dict_is_json_safe_and_rounds_measurements():
    import json

    payload = assess_quality(fixtures_gen.clean_texture()).to_dict()
    assert set(payload) == {
        "width",
        "height",
        "megapixels",
        "min_dimension",
        "blur",
        "brightness",
        "contrast",
        "exposure",
        "warnings",
    }
    assert set(payload["exposure"]) == {
        "clipped_low_fraction",
        "clipped_high_fraction",
        "clipped_fraction",
    }
    json.dumps(payload)  # must not raise


def test_empty_image_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        assess_quality(np.array([], dtype=np.uint8))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_width": 0},
        {"min_height": 0},
        {"min_brightness": 200.0, "max_brightness": 100.0},
        {"max_clipped_fraction": 1.5},
        {"max_clipped_fraction": -0.1},
    ],
)
def test_invalid_thresholds_are_rejected(kwargs):
    with pytest.raises(ValueError):
        QualityThresholds(**kwargs)
