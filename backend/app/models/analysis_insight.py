import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import InsightCapability, InsightMode, InsightProvider, InsightStatus

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")

# prompt_version is never NULL, even for local-only results (stored as ""),
# because PostgreSQL unique constraints treat NULL as distinct from every
# other NULL -- a nullable prompt_version would silently break the cache
# uniqueness policy for local-mode requests (each would insert a new row
# instead of hitting the existing one).
LOCAL_PROMPT_VERSION = ""


class AnalysisJobInsight(Base):
    """Versioned, cached Content Intelligence output for one analysis job.

    Uniqueness (job_id, capability, mode_requested, output_language,
    schema_version, prompt_version) means a repeated identical request always
    returns the same cached row, while bumping INSIGHT_SCHEMA_VERSION or
    INSIGHT_AI_PROMPT_VERSION permits regeneration without deleting history.
    """

    __tablename__ = "analysis_job_insights"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "capability",
            "mode_requested",
            "output_language",
            "schema_version",
            "prompt_version",
            name="uq_insight_cache_key",
        ),
        Index("ix_insight_job_id", "job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE")
    )

    capability: Mapped[InsightCapability] = mapped_column(
        Enum(InsightCapability, native_enum=False, length=32, validate_strings=True)
    )
    mode_requested: Mapped[InsightMode] = mapped_column(
        Enum(InsightMode, native_enum=False, length=16, validate_strings=True)
    )
    mode_used: Mapped[InsightMode] = mapped_column(
        Enum(InsightMode, native_enum=False, length=16, validate_strings=True)
    )
    output_language: Mapped[str] = mapped_column(String(8))

    status: Mapped[InsightStatus] = mapped_column(
        Enum(InsightStatus, native_enum=False, length=16, validate_strings=True)
    )
    schema_version: Mapped[int] = mapped_column(Integer)
    result_json: Mapped[dict] = mapped_column(_JSONVariant)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)

    provider_requested: Mapped[InsightProvider | None] = mapped_column(
        Enum(InsightProvider, native_enum=False, length=16, validate_strings=True), nullable=True
    )
    provider_used: Mapped[InsightProvider | None] = mapped_column(
        Enum(InsightProvider, native_enum=False, length=16, validate_strings=True), nullable=True
    )
    fallback_provider: Mapped[InsightProvider | None] = mapped_column(
        Enum(InsightProvider, native_enum=False, length=16, validate_strings=True), nullable=True
    )
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default=LOCAL_PROMPT_VERSION)
    input_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
