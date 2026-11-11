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

from .models import AnalysisRun, Comparison, Sample, utc_now


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
                base.order_by(Sample.code).limit(limit).offset(offset)
            )
        )
        return items, int(total or 0)

    def soft_delete(self, sample_id: str) -> Sample | None:
        sample = self.get(sample_id)
        if sample is not None and sample.deleted_at is None:
            sample.deleted_at = utc_now()
            self._session.flush()
        return sample


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
    ) -> AnalysisRun:
        run = AnalysisRun(
            sample_id=sample_id,
            pipeline_name=pipeline_name,
            pipeline_version=pipeline_version,
            params=params if params is not None else {},
            status=status,
            input_asset_id=input_asset_id,
        )
        self._session.add(run)
        self._session.flush()
        return run

    def get(self, run_id: str) -> AnalysisRun | None:
        return self._session.get(AnalysisRun, run_id)

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
                base.order_by(AnalysisRun.created_at.desc(), AnalysisRun.id)
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
