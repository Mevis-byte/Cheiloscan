"""Integration tests: model constraints and validation.

Note on ``IntegrityError`` tests: the session context manager commits on
exit, so constraint violations are observed by letting the error propagate
out of the ``with`` block (the context then rolls back).
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy.exc import IntegrityError, StatementError

from cheiloscan.db.models import AnalysisRun, Comparison, ImageAsset, Sample


def _image_kwargs(sha256: str, **overrides) -> dict:
    kwargs = {
        "sha256": sha256,
        "storage_path": f"original/{sha256[:2]}/{sha256}.png",
        "format": "png",
        "width": 640,
        "height": 480,
        "size_bytes": 1024,
    }
    kwargs.update(overrides)
    return kwargs


def test_create_sample_with_all_fields(database):
    with database.session() as session:
        sample = Sample(
            code="S-001",
            research_notes="pilot collection",
            capture_type="print_document",
            medium="lipstick on paper",
            collection_method="light pressure, single lift",
            donor_ref="D-001",
            consent_confirmed=True,
        )
        session.add(sample)
        session.flush()

        assert sample.id
        assert sample.created_at is not None
        assert sample.updated_at is not None
        assert sample.deleted_at is None
        assert sample.consent_confirmed is True
        assert not sample.is_deleted


def test_sample_defaults(database):
    with database.session() as session:
        sample = Sample(code="S-defaults")
        session.add(sample)
        session.flush()
        assert sample.consent_confirmed is False
        assert sample.capture_type is None


def test_sample_code_must_be_unique(database):
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(Sample(code="DUPLICATE"))
            session.add(Sample(code="DUPLICATE"))


def test_sample_ids_are_unique(database):
    with database.session() as session:
        for index in range(5):
            session.add(Sample(code=f"S-{index}"))
    # Re-read committed rows: ids must exist and be distinct.
    with database.session() as session:
        rows = session.query(Sample).order_by(Sample.code).all()
        ids = {row.id for row in rows}
    assert len(ids) == 5 and all(ids)


def test_updated_at_changes_on_modification(database):
    with database.session() as session:
        sample = Sample(code="S-touch")
        session.add(sample)
        session.flush()
        assert sample.updated_at >= sample.created_at

    time.sleep(0.02)  # ensure the clock advances beyond datetime resolution
    with database.session() as session:
        sample = session.query(Sample).filter_by(code="S-touch").one()
        original_updated = sample.updated_at
        sample.research_notes = "updated note"
        session.flush()
        assert sample.updated_at > original_updated


def test_analysis_requires_existing_sample(database):
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                AnalysisRun(
                    sample_id="no-such-sample",
                    pipeline_name="baseline",
                    pipeline_version="1",
                )
            )


def test_analysis_requires_pipeline_identity(database):
    with database.session() as session:
        sample = Sample(code="S-pipe")
        session.add(sample)
        session.flush()

        with pytest.raises(IntegrityError):
            session.add(
                AnalysisRun(sample_id=sample.id, pipeline_name="baseline")
            )
            session.flush()
        session.rollback()


def test_analysis_status_enum_rejects_unknown_values(database):
    with database.session() as session:
        sample = Sample(code="S-status")
        session.add(sample)
        session.flush()
        with pytest.raises((StatementError, LookupError)):
            session.add(
                AnalysisRun(
                    sample_id=sample.id,
                    pipeline_name="baseline",
                    pipeline_version="1",
                    status="vibing",
                )
            )
            session.flush()
        session.rollback()


def test_original_images_deduplicate_by_hash(database):
    with database.session() as session:
        sample = Sample(code="S-img")
        session.add(sample)
        session.flush()
        session.add(
            ImageAsset(sample_id=sample.id, **_image_kwargs("a" * 64))
        )
        session.flush()
        with pytest.raises(IntegrityError):
            session.add(
                ImageAsset(sample_id=sample.id, **_image_kwargs("a" * 64))
            )
            session.flush()
        session.rollback()


def test_derived_images_may_share_a_hash(database):
    with database.session() as session:
        sample = Sample(code="S-derived")
        session.add(sample)
        session.flush()
        session.add(
            ImageAsset(
                sample_id=sample.id, kind="derived", **_image_kwargs("b" * 64)
            )
        )
        session.add(
            ImageAsset(
                sample_id=sample.id, kind="derived", **_image_kwargs("b" * 64)
            )
        )
        session.flush()
        assert len(sample.images) == 2


def test_image_asset_requires_dimensions_and_format(database):
    with database.session() as session:
        sample = Sample(code="S-dims")
        session.add(sample)
        session.flush()
        with pytest.raises(IntegrityError):
            session.add(
                ImageAsset(
                    sample_id=sample.id,
                    sha256="c" * 64,
                    storage_path="original/cc/ccc.png",
                    format="png",
                    width=100,
                )
            )
            session.flush()
        session.rollback()


def test_comparison_requires_both_samples(database):
    with database.session() as session:
        sample_a = Sample(code="S-ca")
        session.add(sample_a)
        session.flush()
        with pytest.raises(IntegrityError):
            session.add(
                Comparison(
                    sample_a_id=sample_a.id,
                    sample_b_id="no-such-sample",
                    method="heuristic_fusion_v1",
                )
            )
            session.flush()
        session.rollback()


def test_hard_delete_of_sample_with_dependents_is_blocked(database):
    """Deletion is soft by design; hard deletion must not silently cascade."""
    with database.session() as session:
        sample = Sample(code="S-guard")
        session.add(sample)
        session.flush()
        session.add(
            AnalysisRun(
                sample_id=sample.id,
                pipeline_name="baseline",
                pipeline_version="1",
            )
        )
        session.flush()
        session.delete(sample)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
