"""Unit tests: preprocessing parameter validation and pipeline execution."""

from __future__ import annotations

import json

import numpy as np
import pytest

from cheiloscan.imaging import pipeline
from cheiloscan.imaging.pipeline import (
    ARTIFACT_ROLES,
    InvalidParameterError,
    PreprocessParams,
    run_pipeline,
)
from tests import fixtures_gen


def test_default_parameters_are_valid_and_complete():
    params = PreprocessParams()
    assert params.denoise in pipeline.DENOISE_METHODS
    assert params.output_format in pipeline.OUTPUT_FORMATS
    assert set(params.to_dict()) == set(PreprocessParams.allowed_keys())


def test_from_mapping_accepts_partial_overrides():
    params = PreprocessParams.from_mapping(
        {"denoise": "median", "denoise_kernel": 7, "gamma": 0.8, "clahe": False}
    )
    assert params.denoise == "median"
    assert params.denoise_kernel == 7
    assert params.gamma == pytest.approx(0.8)
    assert params.clahe is False
    # Unspecified values keep their documented defaults.
    assert params.sharpen is True


def test_from_mapping_none_returns_defaults():
    assert PreprocessParams.from_mapping(None) == PreprocessParams()


def test_from_mapping_rejects_unknown_keys():
    with pytest.raises(InvalidParameterError) as excinfo:
        PreprocessParams.from_mapping({"sharpness": 2})
    assert any("unknown parameter" in message for message in excinfo.value.errors)


@pytest.mark.parametrize(
    ("payload", "needle"),
    [
        ({"denoise": "magic"}, "denoise must be one of"),
        ({"denoise_kernel": 4}, "denoise_kernel"),
        ({"denoise_kernel": 99}, "denoise_kernel"),
        ({"bilateral_diameter": 0}, "bilateral_diameter"),
        ({"bilateral_sigma_color": 0}, "bilateral_sigma_color"),
        ({"illumination_sigma": 0}, "illumination_sigma"),
        ({"illumination_sigma": "wide"}, "illumination_sigma"),
        ({"clahe_clip_limit": 0}, "clahe_clip_limit"),
        ({"clahe_tile_grid_size": 1}, "clahe_tile_grid_size"),
        ({"gamma": 0.1}, "gamma"),
        ({"sharpen_amount": 9}, "sharpen_amount"),
        ({"output_format": "bmp"}, "output_format"),
        ({"output_quality": 0}, "output_quality"),
        ({"clahe": "yes"}, "clahe must be a boolean"),
        ({"gamma": True}, "gamma must be a number"),
        ({"denoise_kernel": 5.5}, "denoise_kernel must be an integer"),
    ],
)
def test_from_mapping_rejects_invalid_values(payload, needle):
    with pytest.raises(InvalidParameterError) as excinfo:
        PreprocessParams.from_mapping(payload)
    assert any(needle in message for message in excinfo.value.errors)


def test_from_mapping_rejects_non_object_payloads():
    with pytest.raises(InvalidParameterError):
        PreprocessParams.from_mapping([1, 2, 3])  # type: ignore[arg-type]


def test_run_pipeline_produces_every_stage_with_real_images():
    source = fixtures_gen.sharp_texture()
    original = source.copy()
    result = run_pipeline(source)

    assert [stage.role for stage in result.stages] == list(ARTIFACT_ROLES)
    for stage in result.stages:
        assert isinstance(stage.image, np.ndarray)
        assert stage.image.size > 0
        assert stage.image.shape[:2] == source.shape[:2]

    assert np.array_equal(source, original), "pipeline must not mutate its input"
    assert result.final_image.shape[:2] == source.shape[:2]
    assert result.final_image.dtype == np.uint8
    assert set(result.timings_ms) == set(ARTIFACT_ROLES) | {"total"}
    assert all(value >= 0 for value in result.timings_ms.values())


def test_run_pipeline_measures_quality_before_and_after():
    result = run_pipeline(fixtures_gen.sharp_texture())
    assert result.quality_before.width == 512
    assert result.quality_after.width == 512
    assert result.quality_before.blur_laplacian_variance >= 0
    assert result.quality_after.blur_laplacian_variance >= 0


def test_disabled_stages_pass_through_and_are_flagged():
    params = PreprocessParams(
        denoise="none",
        illumination_correction=False,
        clahe=False,
        gamma=1.0,
        normalize=False,
        sharpen=False,
    )
    result = run_pipeline(fixtures_gen.mid_gray(64, 64), params)
    for role in ("denoised", "illumination_corrected", "contrast_enhanced", "final"):
        assert result.stage(role).skipped is True, role
    assert result.stage("grayscale").skipped is False
    # With every enhancement disabled the final image equals grayscale.
    assert np.array_equal(result.final_image, result.stage("grayscale").image)
    assert len(result.notes) >= 3


def test_stage_operations_are_recorded():
    result = run_pipeline(
        fixtures_gen.mid_gray(96, 96), PreprocessParams(denoise="gaussian")
    )
    assert "gaussian_blur" in result.stage("denoised").operation
    assert result.stage("illumination_corrected").operation == "correct_illumination"
    assert "clahe" in result.stage("contrast_enhanced").operation
    assert "normalize_image" in result.stage("final").operation


def test_summary_is_json_safe_and_contains_no_image_data():
    result = run_pipeline(fixtures_gen.mid_gray(96, 96))
    summary = result.to_summary()
    encoded = json.dumps(summary)
    assert "pipeline" in summary and summary["pipeline"]["name"]
    assert len(summary["stages"]) == len(ARTIFACT_ROLES)
    assert "quality_before" in summary and "quality_after" in summary
    assert "ndarray" not in encoded


def test_stage_lookup_for_unknown_role_raises():
    result = run_pipeline(fixtures_gen.mid_gray(64, 64))
    with pytest.raises(KeyError):
        result.stage("not-a-stage")


def test_run_pipeline_rejects_empty_input():
    from cheiloscan.imaging.preprocess import PreprocessingError

    with pytest.raises(PreprocessingError):
        run_pipeline(np.array([], dtype=np.uint8))
