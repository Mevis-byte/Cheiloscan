"""Dashboard statistics.

All numbers returned here are real counts and real measured disk usage.
Nothing is estimated, averaged or invented; with an empty database the
result is honestly all zeros (rendered as an empty state by the UI).

No accuracy- or matching-related metrics are included: cheiloscopy is not
a validated biometric method and no dataset exists to compute error rates
(see docs/SCIENTIFIC_METHODOLOGY.md §2, claim policy).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import (
    SCHEMA_VERSION,
    AnalysisRun,
    Comparison,
    ImageAsset,
    Sample,
    utc_now,
)
from ..storage import storage_usage_bytes


@dataclass(frozen=True)
class DashboardStats:
    samples_total: int
    samples_active: int
    images_total: int
    analyses_total: int
    comparisons_total: int
    storage_bytes: int
    schema_version: int
    generated_at: datetime
    analyses_by_status: dict[str, int] = field(default_factory=dict)
    comparisons_by_status: dict[str, int] = field(default_factory=dict)


def _count_by_status(session: Session, model) -> tuple[int, dict[str, int]]:
    rows = session.execute(
        select(model.status, func.count()).group_by(model.status)
    ).all()
    by_status = {str(status): int(count) for status, count in rows}
    return sum(by_status.values()), by_status


def collect_dashboard_stats(session: Session, data_dir: Path) -> DashboardStats:
    """Compute real database counts and storage usage for the dashboard."""
    samples_total = int(
        session.scalar(select(func.count()).select_from(Sample)) or 0
    )
    samples_active = int(
        session.scalar(
            select(func.count())
            .select_from(Sample)
            .where(Sample.deleted_at.is_(None))
        )
        or 0
    )
    images_total = int(
        session.scalar(select(func.count()).select_from(ImageAsset)) or 0
    )
    analyses_total, analyses_by_status = _count_by_status(session, AnalysisRun)
    comparisons_total, comparisons_by_status = _count_by_status(
        session, Comparison
    )
    return DashboardStats(
        samples_total=samples_total,
        samples_active=samples_active,
        images_total=images_total,
        analyses_total=analyses_total,
        analyses_by_status=analyses_by_status,
        comparisons_total=comparisons_total,
        comparisons_by_status=comparisons_by_status,
        storage_bytes=storage_usage_bytes(Path(data_dir)),
        schema_version=SCHEMA_VERSION,
        generated_at=utc_now(),
    )
