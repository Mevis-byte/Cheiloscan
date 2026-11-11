"""Unit tests: content-addressed asset storage and its integrity guards."""

from __future__ import annotations

import os

import pytest

from cheiloscan.storage.asset_store import AssetStore, StorageError
from tests import fixtures_gen


@pytest.fixture
def store(tmp_path):
    return AssetStore(tmp_path / "data")


def test_save_original_is_content_addressed_and_deduplicated(store):
    payload = fixtures_gen.valid_png()
    first = store.save_original(payload, "png")
    assert first.created is True
    assert first.sha256 in first.relative_path
    assert first.relative_path.startswith("original/")
    assert store.read(first.relative_path) == payload

    second = store.save_original(payload, "png")
    assert second.created is False
    assert second.relative_path == first.relative_path
    assert second.sha256 == first.sha256


def test_save_original_rejects_empty_and_unsupported(store):
    with pytest.raises(StorageError, match="empty"):
        store.save_original(b"", "png")
    with pytest.raises(StorageError, match="unsupported"):
        store.save_original(b"data", "bmp")


def test_save_original_refuses_to_overwrite_a_mismatched_file(store):
    payload = fixtures_gen.valid_png()
    stored = store.save_original(payload, "png")
    target = store.resolve(stored.relative_path)

    # Simulate corruption of the stored file (originals are read-only, so a
    # writer would first have to remove that protection).
    os.chmod(target, 0o644)
    target.write_bytes(b"tampered content")

    with pytest.raises(StorageError, match="refusing to overwrite"):
        store.save_original(payload, "png")


def test_save_derived_is_scoped_per_run_and_role(store):
    run_a = "11111111-1111-1111-1111-111111111111"
    run_b = "22222222-2222-2222-2222-222222222222"
    one = store.save_derived(b"a", run_id=run_a, role="grayscale", image_format="png")
    two = store.save_derived(b"b", run_id=run_a, role="final", image_format="png")
    three = store.save_derived(b"c", run_id=run_b, role="final", image_format="png")

    assert one.relative_path == f"derived/{run_a}/grayscale.png"
    assert two.relative_path == f"derived/{run_a}/final.png"
    assert three.relative_path == f"derived/{run_b}/final.png"
    assert store.read(one.relative_path) == b"a"
    assert store.read(three.relative_path) == b"c"


@pytest.mark.parametrize(
    ("run_id", "role"),
    [("../escape", "final"), ("run", "../escape"), ("run", "a/b"), ("", "final")],
)
def test_save_derived_rejects_unsafe_path_components(store, run_id, role):
    with pytest.raises(StorageError):
        store.save_derived(b"x", run_id=run_id, role=role, image_format="png")


@pytest.mark.parametrize(
    "relative",
    ["../outside.txt", "/etc/passwd", "original/../../outside.txt"],
)
def test_resolve_refuses_paths_outside_the_store(store, relative):
    with pytest.raises(StorageError):
        store.resolve(relative)


def test_exists_and_read_report_missing_files(store):
    assert store.exists("original/aa/missing.png") is False
    with pytest.raises(FileNotFoundError):
        store.read("original/aa/missing.png")
