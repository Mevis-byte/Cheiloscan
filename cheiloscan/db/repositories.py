"""Repositories: persistence use-cases per aggregate.

Repositories own all SQLAlchemy query construction so that API routes and
services stay free of ORM details. Every method takes a session-bound
instance; transaction boundaries are managed by the caller (``Database.
session()`` context manager).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .models import (
    AnalysisArtifact,
    AnalysisRun,
    Comparison,
    ImageAsset,
    Sample,
    utc_now,
)


class SampleRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        code: str,
        research_notes: str | None = None,
        capture_type: str | None = None,
        medium: str | None = None,
        collection_method: str | None = None,
        donor_ref: str | None = None,
        consent_confirmed: bool = False,
        captured_at: datetime | None = None,
    ) -> Sample:
        sample = Sample(
            code=code,
            research_notes=research_notes,
            capture_type=capture_type,
            medium=medium,
            collection_method=collection_method,
            donor_ref=donor_ref,
            consent_confirmed=consent_confirmed,
            captured_at=captured_at,
        )
        self._session.add(sample)
        self._session.flush()
        return sample

    def get(self, sample_id: str) -> Sample | None:
        return self._session.get(Sample, sample_id)

    def get_by_code(self, code: str) -> Sample | None:
        return self._session.scalar(select(Sample).where(Sample.code == code))

    def list(
        self,
        *,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Sample], int]:
        """Return (samples, total_count) ordered by ``code`` (stable)."""
        base = select(Sample)
        if not include_deleted:
            base = base.where(Sample.deleted_at.is_(None))
        total = self._session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        items = list(
            self._session.scalars(
                base.options(
                    selectinload(Sample.images), selectinload(Sample.analyses)
                )
                .order_by(Sample.code)
                .limit(limit)
                .offset(offset)
            )
        )
        return items, int(total or 0)

    def soft_delete(self, sample_id: str) -> Sample | None:
        sample = self.get(sample_id)
        if sample is not None and sample.deleted_at is None:
            sample.deleted_at = utc_now()
            self._session.flush()
        return sample


class ImageAssetRepository:
    """Persistence for original and derived image assets."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        sample_id: str,
        sha256: str,
        storage_path: str,
        format: str,
        width: int,
        height: int,
        size_bytes: int,
        kind: str = "original",
        capture_meta: dict | None = None,
        parent_asset_id: str | None = None,
    ) -> ImageAsset:
        asset = ImageAsset(
            sample_id=sample_id,
            kind=kind,
            sha256=sha256,
            storage_path=storage_path,
            format=format,
            width=width,
            height=height,
            size_bytes=size_bytes,
            capture_meta=capture_meta,
            parent_asset_id=parent_asset_id,
        )
        self._session.add(asset)
        self._session.flush()
        return asset

    def get(self, asset_id: str) -> ImageAsset | None:
        return self._session.get(ImageAsset, asset_id)

    def find_original_by_sha256(self, sha256: str) -> ImageAsset | None:
        return self._session.scalar(
            select(ImageAsset)
            .where(ImageAsset.kind == "original", ImageAsset.sha256 == sha256)
            .limit(1)
        )

    def latest_original_for_sample(self, sample_id: str) -> ImageAsset | None:
        return self._session.scalar(
            select(ImageAsset)
            .where(
                ImageAsset.sample_id == sample_id,
                ImageAsset.kind == "original",
            )
            .order_by(ImageAsset.created_at.desc(), ImageAsset.id.desc())
            .limit(1)
        )

    def list_for_sample(
        self, sample_id: str, *, kind: str | None = None
    ) -> list[ImageAsset]:
        query = select(ImageAsset).where(ImageAsset.sample_id == sample_id)
        if kind is not None:
            query = query.where(ImageAsset.kind == kind)
        return list(
            self._session.scalars(
                query.order_by(ImageAsset.created_at, ImageAsset.id)
            )
        )


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        sample_id: str,
        pipeline_name: str,
        pipeline_version: str,
        params: dict | None = None,
        status: str = "pending",
        input_asset_id: str | None = None,
        run_id: str | None = None,
    ) -> AnalysisRun:
        fields: dict[str, object] = {
            "sample_id": sample_id,
            "pipeline_name": pipeline_name,
            "pipeline_version": pipeline_version,
            "params": params if params is not None else {},
            "status": status,
            "input_asset_id": input_asset_id,
        }
        if run_id is not None:
            fields["id"] = run_id
        run = AnalysisRun(**fields)
        self._session.add(run)
        self._session.flush()
        return run

    def get(self, run_id: str) -> AnalysisRun | None:
        return self._session.get(AnalysisRun, run_id)

    def get_with_artifacts(self, run_id: str) -> AnalysisRun | None:
        """Load a run with its artifacts and artifact assets in one query."""
        return self._session.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.id == run_id)
            .options(
                selectinload(AnalysisRun.artifacts).selectinload(
                    AnalysisArtifact.asset
                )
            )
        )

    def add_artifact(
        self, *, run_id: str, image_asset_id: str, role: str
    ) -> AnalysisArtifact:
        artifact = AnalysisArtifact(
            analysis_run_id=run_id,
            image_asset_id=image_asset_id,
            role=role,
        )
        self._session.add(artifact)
        self._session.flush()
        return artifact

    def list_artifacts(self, run_id: str) -> list[AnalysisArtifact]:
        return list(
            self._session.scalars(
                select(AnalysisArtifact)
                .where(AnalysisArtifact.analysis_run_id == run_id)
                .order_by(AnalysisArtifact.role)
            )
        )

    def list(
        self,
        *,
        sample_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AnalysisRun], int]:
        base = select(AnalysisRun)
        if sample_id is not None:
            base = base.where(AnalysisRun.sample_id == sample_id)
        if status is not None:
            base = base.where(AnalysisRun.status == status)
        total = self._session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        items = list(
            self._session.scalars(
                base.options(
                    selectinload(AnalysisRun.sample),
                    selectinload(AnalysisRun.artifacts),
                )
                .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id)
                .limit(limit)
                .offset(offset)
            )
        )
        return items, int(total or 0)


class ComparisonRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        sample_a_id: str,
        sample_b_id: str,
        method: str,
        method_version: str | None = None,
        params: dict | None = None,
        status: str = "pending",
    ) -> Comparison:
        comparison = Comparison(
            sample_a_id=sample_a_id,
            sample_b_id=sample_b_id,
            method=method,
            method_version=method_version,
            params=params,
            status=status,
        )
        self._session.add(comparison)
        self._session.flush()
        return comparison

    def get(self, comparison_id: str) -> Comparison | None:
        return self._session.get(Comparison, comparison_id)

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Comparison], int]:
        base = select(Comparison).options(
            selectinload(Comparison.sample_a), selectinload(Comparison.sample_b)
        )
        if status is not None:
            base = base.where(Comparison.status == status)
        total = self._session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        items = list(
            self._session.scalars(
                base.order_by(Comparison.created_at.desc(), Comparison.id)
                .limit(limit)
                .offset(offset)
            )
        )
        return items, int(total or 0)
