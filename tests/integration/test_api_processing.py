"""Integration tests: processing runs, artifacts, previews and failure paths."""

from __future__ import annotations

import io
import os

from cheiloscan.db.repositories import (
    ImageAssetRepository,
    SampleRepository,
)
from cheiloscan.storage.asset_store import StorageError
from cheiloscan.util.imageio import sha256_hex
from tests import fixtures_gen


def _upload(client, payload: bytes | None = None, code: str | None = None) -> dict:
    data = {
        "file": (
            io.BytesIO(payload if payload is not None else fixtures_gen.valid_png()),
            "sample.png",
        )
    }
    if code:
        data["code"] = code
    response = client.post(
        "/api/samples/upload", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _process(client, sample_id: str, payload=None):
    return client.post(f"/api/analysis/{sample_id}/process", json=payload or {})


def test_process_creates_succeeded_run_with_real_artifacts(client):
    upload = _upload(client)
    response = _process(client, upload["sample"]["id"])
    assert response.status_code == 201, response.get_json()

    body = response.get_json()
    run = body["analysis"]
    assert run["status"] == "succeeded"
    assert run["error"] is None
    assert run["input_asset_id"] == upload["asset"]["id"]
    assert run["started_at"] and run["finished_at"]

    results = run["results"]
    assert results["pipeline"]["name"] == "preprocess_baseline"
    assert results["input"]["sha256"] == upload["asset"]["sha256"]
    assert [stage["role"] for stage in results["stages"]] == [
        "grayscale",
        "denoised",
        "illumination_corrected",
        "contrast_enhanced",
        "final",
    ]
    assert results["quality_before"]["width"] == 512
    assert results["quality_after"]["width"] == 512
    assert results["timings_ms"]["total"] >= 0
    assert results["output"]["format"] == "png"

    artifacts = body["artifacts"]
    assert {item["role"] for item in artifacts} == {
        "grayscale",
        "denoised",
        "illumination_corrected",
        "contrast_enhanced",
        "final",
    }
    for artifact in artifacts:
        assert artifact["asset_id"]
        assert artifact["format"] == "png"
        assert artifact["width"] == 512 and artifact["height"] == 384
        assert artifact["sha256"]
        assert artifact["file_url"] == f"/api/assets/{artifact['asset_id']}/file"


def test_process_accepts_explicit_parameters(client):
    upload = _upload(client)
    response = _process(
        client,
        upload["sample"]["id"],
        {"params": {"denoise": "median", "denoise_kernel": 7, "gamma": 0.9}},
    )
    assert response.status_code == 201
    params = response.get_json()["analysis"]["params"]
    assert params["denoise"] == "median"
    assert params["denoise_kernel"] == 7
    assert params["gamma"] == 0.9


def test_get_analysis_returns_run_artifacts_and_sample(client):
    upload = _upload(client, code="S-READ")
    created = _process(client, upload["sample"]["id"]).get_json()

    response = client.get(f"/api/analysis/{created['analysis']['id']}")
    assert response.status_code == 200
    body = response.get_json()
    assert body["analysis"]["id"] == created["analysis"]["id"]
    assert body["sample"] == {"id": upload["sample"]["id"], "code": "S-READ"}
    assert {item["role"] for item in body["artifacts"]} == {
        "grayscale",
        "denoised",
        "illumination_corrected",
        "contrast_enhanced",
        "final",
    }


def test_get_unknown_analysis_returns_404(client):
    response = client.get("/api/analysis/does-not-exist")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "analysis_not_found"


def test_artifacts_are_served_with_correct_mime_and_bytes(client):
    upload = _upload(client)
    created = _process(client, upload["sample"]["id"]).get_json()
    artifact = next(
        item for item in created["artifacts"] if item["role"] == "final"
    )

    response = client.get(artifact["file_url"])
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert sha256_hex(response.data) == artifact["sha256"]
    assert response.headers["Cache-Control"].startswith("private")

    # The served bytes decode as a real image of the recorded dimensions.
    from cheiloscan.util.imageio import decode_image

    decoded = decode_image(response.data)
    assert (decoded.width, decoded.height) == (artifact["width"], artifact["height"])


def test_serving_unknown_asset_returns_404(client):
    response = client.get("/api/assets/nope/file")
    assert response.status_code == 404


def test_invalid_parameters_are_rejected_before_a_run_is_created(client):
    upload = _upload(client)
    response = _process(client, upload["sample"]["id"], {"gamma": 99})
    assert response.status_code == 400
    error = response.get_json()["error"]
    assert error["code"] == "invalid_parameters"
    assert error["details"]["errors"]

    listing = client.get("/api/analyses").get_json()
    assert listing["total"] == 0


def test_invalid_json_body_is_rejected(client):
    upload = _upload(client)
    response = client.post(
        f"/api/analysis/{upload['sample']['id']}/process",
        data="not json",
        content_type="application/json",
    )
    assert response.status_code == 400


def test_process_unknown_sample_returns_404(client):
    response = _process(client, "no-such-sample")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "sample_not_found"


def test_process_sample_without_image_returns_409(client, database):
    with database.session() as session:
        sample = SampleRepository(session).create(code="S-NO-IMAGE")
        sample_id = sample.id

    response = _process(client, sample_id)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "sample_has_no_image"


def test_failed_run_is_persisted_with_public_error(client, database, app):
    upload = _upload(client)
    store = app.extensions["asset_store"]
    with database.session() as session:
        asset = ImageAssetRepository(session).get(upload["asset"]["id"])
        storage_path = asset.storage_path

    # Corrupt the stored original to force a decode failure during processing.
    target = store.resolve(storage_path)
    os.chmod(target, 0o644)
    target.write_bytes(b"not an image any more")

    response = _process(client, upload["sample"]["id"])
    assert response.status_code == 500
    body = response.get_json()
    assert body["error"]["code"] == "processing_failed"
    analysis_id = body["error"]["details"]["analysis_id"]
    assert body["analysis"]["status"] == "failed"
    assert "not an image" not in body["analysis"]["error"]
    assert str(target) not in response.get_data(as_text=True)

    stored = client.get(f"/api/analysis/{analysis_id}")
    assert stored.status_code == 200
    run = stored.get_json()["analysis"]
    assert run["status"] == "failed"
    assert run["error"]
    assert run["results"] is None
    assert stored.get_json()["artifacts"] == []


def test_partial_artifact_persistence_is_rolled_back(client, database, app, monkeypatch):
    upload = _upload(client)
    store = app.extensions["asset_store"]
    real_save = store.save_derived
    calls = {"count": 0}

    def flaky_save(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise StorageError("simulated storage failure")
        return real_save(*args, **kwargs)

    monkeypatch.setattr(store, "save_derived", flaky_save)

    response = _process(client, upload["sample"]["id"])
    assert response.status_code == 500
    analysis_id = response.get_json()["error"]["details"]["analysis_id"]

    stored = client.get(f"/api/analysis/{analysis_id}").get_json()
    assert stored["analysis"]["status"] == "failed"
    assert stored["artifacts"] == []

    with database.session() as session:
        derived = ImageAssetRepository(session).list_for_sample(
            upload["sample"]["id"], kind="derived"
        )
    assert derived == []


def test_processing_does_not_modify_the_original(client, database, app):
    payload = fixtures_gen.valid_png()
    upload = _upload(client, payload)
    with database.session() as session:
        asset = ImageAssetRepository(session).get(upload["asset"]["id"])
        storage_path = asset.storage_path
        original_sha = asset.sha256

    assert _process(client, upload["sample"]["id"]).status_code == 201

    store = app.extensions["asset_store"]
    stored = store.read(storage_path)
    assert stored == payload
    assert sha256_hex(stored) == original_sha

    with database.session() as session:
        asset = ImageAssetRepository(session).get(upload["asset"]["id"])
        assert asset.sha256 == original_sha
        assert asset.storage_path == storage_path


def test_rerunning_pipeline_creates_a_separate_run_and_artifacts(client, app):
    upload = _upload(client)
    first = _process(client, upload["sample"]["id"]).get_json()
    second = _process(client, upload["sample"]["id"]).get_json()

    assert first["analysis"]["id"] != second["analysis"]["id"]
    assert first["artifacts"][0]["asset_id"] != second["artifacts"][0]["asset_id"]

    store = app.extensions["asset_store"]
    for run in (first, second):
        for artifact in run["artifacts"]:
            assert store.exists(f"derived/{run['analysis']['id']}/{artifact['role']}.png")


def test_list_analyses_supports_filters(client):
    upload_a = _upload(client, fixtures_gen.valid_png(), code="S-A")
    upload_b = _upload(client, fixtures_gen.valid_jpeg(), code="S-B")
    _process(client, upload_a["sample"]["id"])
    _process(client, upload_b["sample"]["id"])

    everything = client.get("/api/analyses").get_json()
    assert everything["total"] == 2
    assert all(item["artifact_count"] == 5 for item in everything["items"])

    filtered = client.get(
        f"/api/analyses?sample_id={upload_a['sample']['id']}"
    ).get_json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["sample"]["code"] == "S-A"

    by_status = client.get("/api/analyses?status=succeeded").get_json()
    assert by_status["total"] == 2
    none = client.get("/api/analyses?status=failed").get_json()
    assert none["total"] == 0


def test_analysis_responses_never_expose_storage_paths(client):
    upload = _upload(client)
    created = _process(client, upload["sample"]["id"]).get_json()
    for path in (
        f"/api/analysis/{created['analysis']['id']}",
        "/api/analyses",
    ):
        raw = client.get(path).get_data(as_text=True)
        assert "storage_path" not in raw
        assert "derived/" not in raw
        assert "original/" not in raw
