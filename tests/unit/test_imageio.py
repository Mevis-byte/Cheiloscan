"""Unit tests: image decoding, format sniffing, filenames and encoding."""

from __future__ import annotations

import pytest

from cheiloscan.util.imageio import (
    ImageDecodeError,
    UnsupportedFormatError,
    apply_exif_orientation,
    decode_image,
    encode_image,
    sanitize_filename,
    sha256_hex,
    sniff_format,
)
from tests import fixtures_gen


def test_sniff_format_recognises_supported_containers():
    assert sniff_format(fixtures_gen.valid_jpeg()) == "jpeg"
    assert sniff_format(fixtures_gen.valid_png()) == "png"
    assert sniff_format(fixtures_gen.valid_webp()) == "webp"


def test_sniff_format_rejects_unknown_and_gif():
    assert sniff_format(b"") is None
    assert sniff_format(fixtures_gen.unsupported_bytes()) is None
    assert sniff_format(fixtures_gen.animated_gif_bytes()) is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\mevis\\photo.jpg", "photo.jpg"),
        ("my lip print (1).png", "my_lip_print_1_.png"),
        ("...hidden...", "hidden"),
        ("", "upload"),
        (None, "upload"),
        ("   ", "upload"),
    ],
)
def test_sanitize_filename_removes_paths_and_hostile_characters(name, expected):
    assert sanitize_filename(name) == expected


def test_sanitize_filename_truncates_long_names_preserving_suffix():
    cleaned = sanitize_filename("a" * 300 + ".png")
    assert cleaned.endswith(".png")
    assert len(cleaned) <= 120


def test_decode_image_returns_bgr_and_metadata():
    payload = fixtures_gen.valid_png()
    decoded = decode_image(payload)
    assert decoded.format == "png"
    assert decoded.bgr.ndim == 3 and decoded.bgr.shape[2] == 3
    assert (decoded.width, decoded.height) == (512, 384)
    assert decoded.size_bytes == len(payload)
    assert decoded.sha256 == sha256_hex(payload)
    assert decoded.orientation == 1


def test_decode_image_does_not_modify_input_bytes():
    payload = fixtures_gen.valid_jpeg()
    original = bytes(payload)
    decode_image(payload)
    assert payload == original


def test_decode_image_applies_exif_orientation_to_working_copy():
    payload = fixtures_gen.with_exif_orientation(orientation=6, width=320, height=240)
    decoded = decode_image(payload)
    # Stored pixels are 320x240; orientation 6 rotates 90 degrees clockwise.
    assert (decoded.width, decoded.height) == (240, 320)
    assert decoded.exif["orientation"] == 6
    assert decoded.exif["make"] == "SyntheticMake"
    assert decoded.exif["datetime_original"] == "2026:01:02 03:04:05"


def test_decode_image_empty_raises_decode_error():
    with pytest.raises(ImageDecodeError):
        decode_image(b"")


def test_decode_image_unsupported_raises_unsupported_format():
    with pytest.raises(UnsupportedFormatError):
        decode_image(fixtures_gen.unsupported_bytes())


@pytest.mark.parametrize(
    "payload",
    [fixtures_gen.corrupt_png(), fixtures_gen.truncated_png()],
    ids=["garbage-body", "truncated"],
)
def test_decode_image_corrupt_raises_decode_error(payload):
    with pytest.raises(ImageDecodeError):
        decode_image(payload)


def test_encode_image_roundtrips_supported_formats():
    import numpy as np

    image = np.zeros((24, 32, 3), dtype=np.uint8)
    image[:, :] = (10, 120, 220)
    for fmt in ("png", "jpeg", "webp"):
        payload = encode_image(image, fmt, quality=95)
        decoded = decode_image(payload)
        assert decoded.format == fmt
        assert (decoded.width, decoded.height) == (32, 24)


def test_encode_image_rejects_unknown_format():
    import numpy as np

    with pytest.raises(UnsupportedFormatError):
        encode_image(np.zeros((4, 4, 3), dtype=np.uint8), "bmp")


def test_apply_exif_orientation_identity_for_unknown_value():
    import numpy as np

    image = np.arange(24, dtype=np.uint8).reshape(2, 4, 3)
    assert apply_exif_orientation(image, 1) is image
    assert apply_exif_orientation(image, 99) is image


def test_sha256_hex_is_stable_and_lowercase():
    digest = sha256_hex(b"cheiloscan")
    assert digest == sha256_hex(b"cheiloscan")
    assert len(digest) == 64
    assert digest == digest.lower()
