import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class DatasetAnalysis(Base):
    """One completed Universal Dataset Intelligence analysis, written once by
    the worker and read many times afterwards.

    Sectioned rather than one blob. Each result page reads one or two of
    these columns, and the largest of them (column profiles on a 100-column
    upload, the correlation matrix, the chart specs) are the ones a summary
    view never needs -- so the API defers them and a History reopen costs an
    Overview-sized read, not a whole-analysis one.

    Keyed by job_id, exactly like AnalysisJobResult: a dataset analysis
    belongs to the RUN that produced it, so re-running against the same
    dataset produces a second, independently viewable result rather than
    overwriting the first. `dataset_id` is carried alongside so a future
    dataset-scoped view can find every analysis of the same source without
    walking jobs.

    Never holds the uploaded file or a copy of its rows -- `preview_rows` is
    a bounded, sanitized sample (see engine._build_preview) and nothing else
    here reproduces the source data.
    """

    __tablename__ = "dataset_analyses"
    __table_args__ = (
        Index("ix_dataset_analysis_dataset_id", "dataset_id"),
        Index("ix_dataset_analysis_created_at", "created_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_datasets.id", ondelete="SET NULL"), nullable=True
    )
    file_import_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("file_imports.id", ondelete="SET NULL"), nullable=True
    )

    schema_version: Mapped[int] = mapped_column(Integer, default=1)

    # Denormalized headline numbers. These are what History and the Overview
    # header show, and duplicating them here means those reads never have to
    # open a JSON section at all.
    source_kind: Mapped[str] = mapped_column(String(32))
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    column_count: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_row_count: Mapped[int] = mapped_column(Integer, default=0)
    health_score: Mapped[int] = mapped_column(Integer, default=0)
    missing_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    duplicate_row_count: Mapped[int] = mapped_column(Integer, default=0)
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    insights_generated_by: Mapped[str] = mapped_column(String(32), default="deterministic")
    analysis_duration_ms: Mapped[float] = mapped_column(Float, default=0.0)

    overview_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    coverage_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    columns_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    quality_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    cleaning_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    relationships_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    temporal_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    text_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    charts_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    insights_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    preview_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
