"""Integration tests: image upload, validation, deduplication and metadata."""

from __future__ import annotations

import io

import pytest

from cheiloscan.db.repositories import ImageAssetRepository, SampleRepository
from cheiloscan.util.imageio import sha256_hex
from tests import fixtures_gen


def _upload(client, payload: bytes, filename: str = "sample.png", **form):
    data = {"file": (io.BytesIO(payload), filename), **form}
    return client.post(
        "/api/samples/upload", data=data, content_type="multipart/form-data"
    )


def _stored_asset(database, asset_id: str):
    with database.session() as session:
        return ImageAssetRepository(session).get(asset_id)


def test_upload_rejects_images_above_the_pixel_budget(client, app):
    app.config["MAX_IMAGE_PIXELS"] = 1_000
    response = _upload(client, fixtures_gen.valid_png())
    assert response.status_code == 422
    body = response.get_json()
    assert body["error"]["code"] == "image_dimensions_invalid"
    assert body["error"]["details"]["max_pixels"] == 1_000


def test_upload_valid_png_creates_sample_and_original(client, database):
    payload = fixtures_gen.valid_png()
    response = _upload(client, payload, "lip print.png")
    assert response.status_code == 201, response.get_json()

    body = response.get_json()
    assert body["sample"]["code"].startswith("S-")
    assert body["asset"]["kind"] == "original"
    assert body["asset"]["format"] == "png"
    assert body["asset"]["sha256"] == sha256_hex(payload)
    assert body["asset"]["size_bytes"] == len(payload)
    assert (body["asset"]["width"], body["asset"]["height"]) == (512, 384)
    assert body["asset"]["file_url"].endswith("/file")
    assert body["asset"]["original_filename"] == "lip_print.png"
    assert isinstance(body["warnings"], list)
    assert body["quality"]["blur"]["laplacian_variance"] > 0

    raw = response.get_data(as_text=True)
    assert "storage_path" not in raw
    assert "original/" not in raw

    asset = _stored_asset(database, body["asset"]["id"])
    assert asset is not None
    assert asset.sample_id == body["sample"]["id"]


@pytest.mark.parametrize(
    ("fmt", "filename"),
    [("jpeg", "capture.jpg"), ("webp", "capture.webp")],
)
def test_upload_accepts_jpeg_and_webp(client, fmt, filename):
    payload = fixtures_gen.encode(fixtures_gen.sharp_texture(), fmt)
    response = _upload(client, payload, filename)
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["asset"]["format"] == fmt


def test_upload_accepts_explicit_metadata(client):
    response = _upload(
        client,
        fixtures_gen.valid_png(),
        code="  S-EXPLICIT  ",
        capture_type="photograph",
        medium="lipstick on paper",
        collection_method="direct",
        donor_ref="D-001",
        consent_confirmed="true",
        captured_at="2026-01-02T03:04:05Z",
        research_notes="synthetic fixture",
    )
    assert response.status_code == 201
    sample = response.get_json()["sample"]
    assert sample["code"] == "S-EXPLICIT"
    assert sample["capture_type"] == "photograph"
    assert sample["medium"] == "lipstick on paper"
    assert sample["consent_confirmed"] is True
    assert sample["captured_at"].startswith("2026-01-02T03:04:05")


def test_upload_different_dimensions_is_accepted(client):
    payload = fixtures_gen.encode(fixtures_gen.sharp_texture(640, 360), "png")
    response = _upload(client, payload)
    assert response.status_code == 201
    asset = response.get_json()["asset"]
    assert (asset["width"], asset["height"]) == (640, 360)


def test_upload_duplicate_content_conflicts(client):
    payload = fixtures_gen.valid_png()
    first = _upload(client, payload)
    assert first.status_code == 201

    second = _upload(client, payload)
    assert second.status_code == 409
    error = second.get_json()["error"]
    assert error["code"] == "duplicate_image"
    assert error["details"]["existing_sample_id"] == first.get_json()["sample"]["id"]


def test_upload_duplicate_explicit_code_conflicts(client):
    first = _upload(client, fixtures_gen.valid_png(), code="S-DUP")
    assert first.status_code == 201
    # Different bytes so the content-dedup check cannot be the cause.
    second = _upload(client, fixtures_gen.valid_jpeg(), code="S-DUP")
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "sample_code_conflict"


def test_upload_empty_file_is_rejected(client):
    response = _upload(client, b"", "empty.png")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_request"


def test_upload_corrupt_image_is_rejected(client):
    response = _upload(client, fixtures_gen.corrupt_png(), "corrupt.png")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_image"


def test_upload_truncated_image_is_rejected(client):
    response = _upload(client, fixtures_gen.truncated_png(), "truncated.png")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_image"


def test_upload_unsupported_format_is_rejected(client):
    response = _upload(client, fixtures_gen.unsupported_bytes(), "fake.png")
    assert response.status_code == 415
    assert response.get_json()["error"]["code"] == "unsupported_format"


def test_upload_mislabelled_extension_uses_magic_bytes(client):
    # A real PNG named .jpg is accepted as PNG, not rejected.
    response = _upload(client, fixtures_gen.valid_png(), "actually_a_png.jpg")
    assert response.status_code == 201
    assert response.get_json()["asset"]["format"] == "png"


def test_upload_too_small_image_is_rejected(client):
    response = _upload(client, fixtures_gen.tiny_png(64), "tiny.png")
    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["code"] == "image_dimensions_invalid"
    assert error["details"]["min_dimension"] == 128


def test_upload_oversized_dimensions_is_rejected(app, client):
    app.config["MAX_IMAGE_DIMENSION"] = 200
    response = _upload(client, fixtures_gen.valid_png(), "large.png")
    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["code"] == "image_dimensions_invalid"
    assert error["details"]["max_dimension"] == 200


def test_upload_over_request_limit_is_rejected(app, client):
    app.config["MAX_CONTENT_LENGTH"] = 512
    response = _upload(client, fixtures_gen.valid_png(), "big.png")
    assert response.status_code == 413
    assert response.get_json()["error"]["code"] == "file_too_large"


@pytest.mark.parametrize(
    ("form", "field"),
    [
        ({"capture_type": "selfie"}, "capture_type"),
        ({"captured_at": "not-a-date"}, "captured_at"),
        ({"code": "S" * 121}, "code"),
        ({"research_notes": "x" * 10_001}, "research_notes"),
    ],
)
def test_upload_invalid_metadata_is_rejected(client, form, field):
    response = _upload(client, fixtures_gen.valid_png(), **form)
    assert response.status_code == 400
    error = response.get_json()["error"]
    assert error["code"] == "invalid_sample_metadata"
    assert error["details"]["field"] == field


def test_upload_blank_code_falls_back_to_auto_generated(client):
    response = _upload(client, fixtures_gen.valid_png(), code="   ")
    assert response.status_code == 201
    assert response.get_json()["sample"]["code"].startswith("S-")


def test_upload_missing_file_field_is_rejected(client):
    response = client.post("/api/samples/upload", data={})
    assert response.status_code == 400


def test_upload_blurry_and_low_contrast_are_warnings_not_rejections(client):
    blurry = _upload(client, fixtures_gen.encode(fixtures_gen.blurry(), "png"))
    assert blurry.status_code == 201
    codes = {warning["code"] for warning in blurry.get_json()["warnings"]}
    assert "blurry" in codes

    low = _upload(client, fixtures_gen.encode(fixtures_gen.low_contrast(), "png"))
    assert low.status_code == 201
    codes = {warning["code"] for warning in low.get_json()["warnings"]}
    assert "low_contrast" in codes


def test_uploaded_original_bytes_are_preserved_on_disk(client, database, app):
    payload = fixtures_gen.valid_png()
    body = _upload(client, payload).get_json()
    asset = _stored_asset(database, body["asset"]["id"])
    store = app.extensions["asset_store"]

    stored = store.read(asset.storage_path)
    assert stored == payload
    assert sha256_hex(stored) == asset.sha256
    # Originals are write-protected on a best-effort basis.
    mode = store.resolve(asset.storage_path).stat().st_mode
    assert mode & 0o200 == 0


def test_samples_listing_includes_uploaded_image(client, database):
    _upload(client, fixtures_gen.valid_png(), code="S-LISTED")
    body = client.get("/api/samples").get_json()
    assert body["total"] == 1
    sample = body["items"][0]
    assert sample["code"] == "S-LISTED"
    assert sample["image_count"] == 1
    assert sample["images"][0]["kind"] == "original"
    assert sample["images"][0]["quality"] is not None


def test_upload_does_not_create_sample_when_image_is_rejected(client, database):
    _upload(client, fixtures_gen.unsupported_bytes(), "bad.png")
    with database.session() as session:
        samples, total = SampleRepository(session).list()
    assert total == 0 and samples == []
