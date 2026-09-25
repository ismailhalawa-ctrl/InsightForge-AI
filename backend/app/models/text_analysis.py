import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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


class TextAnalysis(Base):
    """One completed Pasted Text Intelligence analysis, written once by the
    worker and read many times afterwards.

    Keyed by job_id exactly like DatasetAnalysis and WebPageAnalysis: an
    analysis belongs to the RUN that produced it, so analysing an edited
    version of the same text later produces a second, independently viewable
    result instead of overwriting the first.

    Sectioned rather than one blob, for the same reason the other two are:
    the result header and History read the denormalized columns and never
    open a JSON section, and each result section requests the one part it
    renders.

    THE TEXT ITSELF IS NOT DUPLICATED HERE. It already lives in
    `paste_text_requests.text`, which is the input of record for this
    analysis; what this row stores is the bounded RESULT -- measurements,
    structure, findings, evidence, the AI reading -- plus a display excerpt.
    """

    __tablename__ = "text_analyses"
    __table_args__ = (
        Index("ix_text_analysis_dataset_id", "dataset_id"),
        Index("ix_text_analysis_created_at", "created_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_datasets.id", ondelete="SET NULL"), nullable=True
    )

    schema_version: Mapped[int] = mapped_column(Integer, default=1)

    # --- denormalized summary: History, the result header and the workspace
    # --- overview read these and never open a JSON section.
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language_state: Mapped[str] = mapped_column(String(16), default="detected")
    language_mixed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    character_count: Mapped[int] = mapped_column(Integer, default=0)
    sentence_count: Mapped[int] = mapped_column(Integer, default=0)
    paragraph_count: Mapped[int] = mapped_column(Integer, default=0)
    heading_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_word_count: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    analysis_duration_ms: Mapped[float] = mapped_column(Float, default=0.0)

    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    strength_count: Mapped[int] = mapped_column(Integer, default=0)
    high_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    medium_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    low_finding_count: Mapped[int] = mapped_column(Integer, default=0)

    ai_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_generated_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ai_topic_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_insight_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_recommendation_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_duration_ms: Mapped[float] = mapped_column(Float, default=0.0)

    # --- sections
    overview_json: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)
    structure_json: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)
    metrics_json: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)
    findings_json: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)
    coverage_json: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)
    ai_json: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
