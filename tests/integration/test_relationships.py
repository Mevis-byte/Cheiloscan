"""Integration tests: ORM relationships and repository behavior."""

from __future__ import annotations

from datetime import datetime

from cheiloscan.db.models import AnalysisRun, ImageAsset, Sample
from cheiloscan.db.repositories import (
    AnalysisRepository,
    ComparisonRepository,
    SampleRepository,
)


def _seed_sample(session, code: str) -> Sample:
    return SampleRepository(session).create(code=code)


def test_sample_images_relationship(database):
    with database.session() as session:
        sample = _seed_sample(session, "R-img")
        for index in range(3):
            session.add(
                ImageAsset(
                    sample_id=sample.id,
                    sha256=f"{index:064d}",
                    storage_path=f"original/{index}/x.png",
                    format="png",
                    width=10,
                    height=10,
                    size_bytes=10,
                )
            )
        session.flush()
        assert len(sample.images) == 3
        assert all(image.sample_id == sample.id for image in sample.images)
        assert all(image.sample.code == "R-img" for image in sample.images)


def test_sample_analyses_relationship_and_input_asset_link(database):
    with database.session() as session:
        sample = _seed_sample(session, "R-run")
        image = ImageAsset(
            sample_id=sample.id,
            sha256="1" * 64,
            storage_path="original/11/x.png",
            format="png",
            width=10,
            height=10,
            size_bytes=10,
        )
        session.add(image)
        session.flush()

        run_a = AnalysisRepository(session).create(
            sample_id=sample.id,
            pipeline_name="baseline",
            pipeline_version="1",
            status="succeeded",
            input_asset_id=image.id,
        )
        AnalysisRepository(session).create(
            sample_id=sample.id,
            pipeline_name="baseline",
            pipeline_version="1",
            status="failed",
        )
        session.flush()

        assert len(sample.analyses) == 2
        assert {str(run.status) for run in sample.analyses} == {
            "succeeded",
            "failed",
        }
        assert run_a.input_asset is not None
        assert run_a.input_asset.id == image.id
        assert run_a.params == {}


def test_comparison_sample_relationships(database):
    with database.session() as session:
        sample_a = _seed_sample(session, "R-cmp-a")
        sample_b = _seed_sample(session, "R-cmp-b")
        comparison = ComparisonRepository(session).create(
            sample_a_id=sample_a.id,
            sample_b_id=sample_b.id,
            method="heuristic_fusion_v1",
            method_version="1",
        )
        session.flush()

        assert comparison.sample_a.code == "R-cmp-a"
        assert comparison.sample_b.code == "R-cmp-b"
        assert str(comparison.status) == "pending"


def test_repository_list_orders_by_code_and_paginates(database):
    with database.session() as session:
        repository = SampleRepository(session)
        for code in ("C-3", "C-1", "C-2"):
            repository.create(code=code)

        items, total = repository.list()
        assert total == 3
        assert [sample.code for sample in items] == ["C-1", "C-2", "C-3"]

        page, total = repository.list(limit=1, offset=1)
        assert total == 3
        assert [sample.code for sample in page] == ["C-2"]


def test_repository_soft_delete_hides_from_default_list(database):
    with database.session() as session:
        repository = SampleRepository(session)
        kept = repository.create(code="keep")
        gone = repository.create(code="gone")
        repository.soft_delete(gone.id)
        session.flush()

        items, total = repository.list()
        assert total == 1
        assert [sample.code for sample in items] == ["keep"]

        items_all, total_all = repository.list(include_deleted=True)
        assert total_all == 2
        assert {sample.code for sample in items_all} == {"keep", "gone"}

        deleted = repository.get(gone.id)
        assert deleted is not None and deleted.is_deleted

        # Soft-deleting twice is a no-op (timestamp not overwritten).
        first_deleted_at = deleted.deleted_at
        repository.soft_delete(gone.id)
        assert deleted.deleted_at == first_deleted_at
        assert repository.get(kept.id).deleted_at is None


def test_analysis_repository_filters_by_sample_and_status(database):
    with database.session() as session:
        sample = _seed_sample(session, "R-filter")
        analysis_repository = AnalysisRepository(session)
        analysis_repository.create(
            sample_id=sample.id,
            pipeline_name="p",
            pipeline_version="1",
            status="succeeded",
        )
        analysis_repository.create(
            sample_id=sample.id,
            pipeline_name="p",
            pipeline_version="1",
            status="pending",
        )

        succeeded, total = analysis_repository.list(status="succeeded")
        assert total == 1 and str(succeeded[0].status) == "succeeded"

        all_runs, total = analysis_repository.list(sample_id=sample.id)
        assert total == 2

        other, total = analysis_repository.list(sample_id="none")
        assert total == 0 and other == []


def test_repository_captures_captured_at_and_notes(database):
    captured_at = datetime(2026, 11, 1, 12, 0, 0)
    with database.session() as session:
        repository = SampleRepository(session)
        repository.create(
            code="R-meta",
            research_notes="notes",
            capture_type="photograph",
            medium="digital camera",
            captured_at=captured_at,
            consent_confirmed=True,
        )

    with database.session() as session:  # fresh session: persisted values
        sample = SampleRepository(session).get_by_code("R-meta")
        assert sample.research_notes == "notes"
        assert sample.capture_type == "photograph"
        assert sample.captured_at == captured_at
        assert sample.consent_confirmed is True
