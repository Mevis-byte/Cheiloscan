"""SQLAlchemy models for CheiloScan.

Entity mapping (see docs/ARCHITECTURE.md §6.2 and the Phase 1 instruction):

- ``Sample``      — a registered lip-print sample (research unit of work),
                    including the instruction's "unique sample identifier"
                    (``code``), "research notes", "consent status" and
                    "capture date".
- ``ImageAsset``  — an image belonging to a sample. Holds the instruction's
                    SAMPLE fields "original image path" (internal,
                    never exposed via the API), "image format" and
                    "image dimensions", plus integrity data (SHA-256).
- ``AnalysisRun`` — the instruction's ANALYSIS entity: sample reference,
                    processing status, processing configuration
                    (pipeline name/version + parameter snapshot) and analysis
                    metadata (lifecycle timestamps, error text).
- ``Comparison``  — the instruction's COMPARISON entity: sample pair,
                    comparison method, results and status.
- ``AnalysisArtifact`` — association row binding a derived image asset to
                    the analysis run and pipeline stage that produced it
                    (added in schema v2, Phase 2).
- ``SchemaVersion``— schema bookkeeping for safe initialization.

Deferred from the Phase 0 schema (added in their implementing phases, so
that no unused/placeholder code exists now):

- ``FeatureSet``  (analysis results, Phase 6)
- ``Report``      (PDF reports, Phase 8)

Phase 1 planned ``ImageAsset.analysis_run_id`` as the reverse run link for
derived assets. That pair of mutually referencing foreign keys cannot be
added to SQLite after the fact, so Phase 2 introduced the
``AnalysisArtifact`` association table instead (schema v2).

All timestamps are stored as naive UTC datetimes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SaEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


#: Current application schema version. Bump on any schema change and record
#: the migration in docs/DEVELOPMENT_LOG.md.
SCHEMA_VERSION = 2


def new_uuid() -> str:
    """Return a new random UUID string (primary key generator)."""
    return str(uuid4())


def utc_now() -> datetime:
    """Naive UTC timestamp (SQLite stores naive datetimes)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base for all CheiloScan models."""


class TimestampMixin:
    """Creation and update timestamps on every entity."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )


class SchemaVersion(Base):
    """Single-row table recording the database schema version."""

    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )


class Sample(TimestampMixin, Base):
    """A registered lip-print sample (the research unit of work).

    A sample may have several images (original captures and derived
    processing artifacts) and analysis runs. Deletion is soft
    (``deleted_at``); the record and its provenance are retained.
    """

    __tablename__ = "samples"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_uuid
    )
    # Unique sample identifier chosen by the researcher.
    code: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    research_notes: Mapped[str | None] = mapped_column(Text)
    capture_type: Mapped[str | None] = mapped_column(
        SaEnum(
            "print_document",
            "photograph",
            name="sample_capture_type",
            validate_strings=True,
        )
    )
    medium: Mapped[str | None] = mapped_column(String(255))
    collection_method: Mapped[str | None] = mapped_column(String(255))
    donor_ref: Mapped[str | None] = mapped_column(String(120))
    consent_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    captured_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    images: Mapped[list[ImageAsset]] = relationship(
        back_populates="sample",
        order_by="ImageAsset.created_at",
        cascade="save-update, merge",
    )
    analyses: Mapped[list[AnalysisRun]] = relationship(
        back_populates="sample",
        order_by="AnalysisRun.created_at",
        cascade="save-update, merge",
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class ImageAsset(TimestampMixin, Base):
    """An image belonging to a sample (original capture or derived artifact).

    ``storage_path`` is an internal path relative to the configured data
    directory. It is deliberately never serialized to API responses.
    Originals are content-addressed by ``sha256``; the partial unique index
    below enforces that two *originals* never share a hash (deduplication
    invariant) while allowing derived artifacts to repeat hashes.
    """

    __tablename__ = "image_assets"
    __table_args__ = (
        Index(
            "uq_original_assets_sha256",
            "sha256",
            unique=True,
            sqlite_where=text("kind = 'original'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("samples.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        SaEnum("original", "derived", name="asset_kind", validate_strings=True),
        nullable=False,
        default="original",
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    capture_meta: Mapped[dict | None] = mapped_column(JSON)
    # Derived artifacts point at the asset they were computed from.
    parent_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id", ondelete="RESTRICT"), nullable=True
    )

    sample: Mapped[Sample] = relationship(back_populates="images")


class AnalysisRun(TimestampMixin, Base):
    """A recorded processing run over a sample's image.

    ``params`` is a complete parameter snapshot taken when the run was
    created, not a reference to current defaults, so the run remains
    reproducible. ``input_asset_id`` is set when the run executes on a
    concrete image (image intake arrives in Phase 3).
    """

    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("samples.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    input_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    pipeline_name: Mapped[str] = mapped_column(String(120), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(40), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Measured outputs of the run (quality before/after, stage timings, notes).
    # Kept separate from ``params`` (the input snapshot) so inputs and outputs
    # are never mixed in one field.
    results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        SaEnum(
            "pending",
            "running",
            "succeeded",
            "failed",
            name="analysis_status",
            validate_strings=True,
        ),
        nullable=False,
        default="pending",
    )
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    sample: Mapped[Sample] = relationship(back_populates="analyses")
    input_asset: Mapped[ImageAsset | None] = relationship()
    artifacts: Mapped[list[AnalysisArtifact]] = relationship(
        back_populates="run",
        order_by="AnalysisArtifact.role",
        cascade="save-update, merge",
    )


class AnalysisArtifact(TimestampMixin, Base):
    """A derived image produced by an analysis run, addressed by its role.

    One row per pipeline stage output (``grayscale``, ``denoised``,
    ``illumination_corrected``, ``contrast_enhanced``, ``final``). The
    unique constraint on ``(analysis_run_id, role)`` guarantees a run has at
    most one artifact per stage; the artifact itself points at a normal
    ``ImageAsset`` (kind ``derived``) so hashing, storage and serving are
    shared with originals.

    This is the Phase 2 replacement for the deferred
    ``ImageAsset.analysis_run_id`` reverse link noted in Phase 1: an
    association table avoids mutually referencing foreign keys, which SQLite
    cannot add after the fact.
    """

    __tablename__ = "analysis_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id", "role", name="uq_analysis_artifact_role"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    image_asset_id: Mapped[str] = mapped_column(
        ForeignKey("image_assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="artifacts")
    asset: Mapped[ImageAsset] = relationship()


class Comparison(TimestampMixin, Base):
    """A pairwise comparison record between two samples.

    Phase 1 stores the sample pair (per the Phase 1 instruction). The
    concrete analysis-run references (``run_a_id``/``run_b_id``) are filled
    by the comparison engine when it is implemented (Phase 7); comparing
    runs rather than raw samples is the documented design because a sample
    can carry multiple images and analysis runs.
    """

    __tablename__ = "comparisons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sample_a_id: Mapped[str] = mapped_column(
        ForeignKey("samples.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sample_b_id: Mapped[str] = mapped_column(
        ForeignKey("samples.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    run_a_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    run_b_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    method: Mapped[str] = mapped_column(String(120), nullable=False)
    method_version: Mapped[str | None] = mapped_column(String(40))
    params: Mapped[dict | None] = mapped_column(JSON)
    component_scores: Mapped[dict | None] = mapped_column(JSON)
    fused_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        SaEnum(
            "pending",
            "running",
            "completed",
            "failed",
            name="comparison_status",
            validate_strings=True,
        ),
        nullable=False,
        default="pending",
    )
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    sample_a: Mapped[Sample] = relationship(foreign_keys=[sample_a_id])
    sample_b: Mapped[Sample] = relationship(foreign_keys=[sample_b_id])
