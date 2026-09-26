import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
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


class WebPageAnalysis(Base):
    """One completed Web Intelligence analysis, written once by the worker
    and read many times afterwards.

    Keyed by job_id exactly like DatasetAnalysis and AnalysisJobResult: an
    analysis belongs to the RUN that produced it, so re-analyzing the same
    URL later produces a second, independently viewable result instead of
    overwriting the first. A page changes; two runs against it are two
    different observations and the product must be able to show both.

    Sectioned rather than one blob, for the same reason the dataset analysis
    is: the result header and History read the denormalized columns and never
    open a JSON section, and each result section requests the one part it
    renders rather than the whole analysis.

    Never stores the page's raw HTML. What is kept is the extracted, bounded
    result -- text, structure, metadata, evidence -- so the row size is
    governed by the analysis limits rather than by whatever the remote server
    chose to send.
    """

    __tablename__ = "web_page_analyses"
    __table_args__ = (
        Index("ix_web_page_analysis_dataset_id", "dataset_id"),
        Index("ix_web_page_analysis_created_at", "created_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_datasets.id", ondelete="SET NULL"), nullable=True
    )

    schema_version: Mapped[int] = mapped_column(Integer, default=1)

    requested_url: Mapped[str] = mapped_column(String(2048))
    final_url: Mapped[str] = mapped_column(String(2048))
    http_status: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)

    page_type: Mapped[str] = mapped_column(String(32), default="unknown")
    page_type_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    main_content_strategy: Mapped[str] = mapped_column(String(32), default="document_body")
    main_content_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    word_count: Mapped[int] = mapped_column(Integer, default=0)
    link_count: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    form_count: Mapped[int] = mapped_column(Integer, default=0)
    heading_count: Mapped[int] = mapped_column(Integer, default=0)
    structured_data_block_count: Mapped[int] = mapped_column(Integer, default=0)
    redirect_count: Mapped[int] = mapped_column(Integer, default=0)
    response_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    dynamic_content_suspected: Mapped[bool] = mapped_column(Boolean, default=False)
    javascript_rendering_performed: Mapped[bool] = mapped_column(Boolean, default=False)

    analysis_duration_ms: Mapped[float] = mapped_column(Float, default=0.0)

    intelligence_schema_version: Mapped[int] = mapped_column(Integer, default=0)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    strength_count: Mapped[int] = mapped_column(Integer, default=0)
    critical_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    high_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    medium_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    low_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    intelligence_duration_ms: Mapped[float] = mapped_column(Float, default=0.0)

    specialization_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    specialization_domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    specialized_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    specialized_strength_count: Mapped[int] = mapped_column(Integer, default=0)

    ai_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    ai_generated_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    ai_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ai_insight_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_priority_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_duration_ms: Mapped[float] = mapped_column(Float, default=0.0)

    target_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    transport_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    metadata_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    content_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    structure_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    structured_data_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    dynamic_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    classification_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    evidence_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    coverage_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    intelligence_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    findings_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    charts_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    specialization_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    ai_json: Mapped[dict] = mapped_column(_JSONVariant, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
