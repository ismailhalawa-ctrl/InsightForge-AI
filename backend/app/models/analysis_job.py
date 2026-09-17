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
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import (
    CollectionMode,
    CommentOrder,
    JobStage,
    JobStatus,
    SentimentMode,
    SourceType,
)

# Real JSONB on PostgreSQL; plain JSON on any other dialect (SQLite in fast
# offline unit tests) since JSONB has no SQLite compiler support.
_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        # Sprint 28: every atomic admission/retry transaction counts this
        # user's active jobs (status NOT IN terminal) while holding the
        # per-user advisory lock -- a composite index lets that count use a
        # single index scan instead of combining the pre-existing separate
        # user_id and status indexes, keeping the lock's hold time short.
        Index("ix_analysis_jobs_user_id_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Nullable to accommodate legacy pre-Sprint-13 rows during backfill; the
    # migration assigns a deterministic system-user id to every existing row,
    # so in practice this is never NULL after upgrade (see README "Legacy
    # data ownership"). Workers keep running without an HTTP user context and
    # never need to set this themselves -- it is assigned only at job-creation
    # time from the authenticated principal.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False, length=32, validate_strings=True)
    )
    source_reference: Mapped[str] = mapped_column(String(2048))
    source_external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Nullable so legacy pre-Sprint-15 jobs remain valid without a backfilled
    # dataset for every historical row (see the Sprint 15 migration's backfill
    # policy). New jobs resolve/create a SourceDataset at creation time.
    source_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_datasets.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )

    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=32, validate_strings=True),
        default=JobStatus.queued,
        index=True,
    )
    stage: Mapped[JobStage] = mapped_column(
        Enum(JobStage, native_enum=False, length=32, validate_strings=True),
        default=JobStage.validating_source,
    )
    collection_mode: Mapped[CollectionMode] = mapped_column(
        Enum(CollectionMode, native_enum=False, length=32, validate_strings=True),
        default=CollectionMode.bounded,
    )
    # True for jobs created against an already-populated SourceDataset (see
    # POST /analysis/jobs/from-dataset) -- the runner skips
    # validate_source/collect_page entirely and reads existing SourceRecords
    # directly (AnalysisJobRunner._run_job). False (default) preserves every
    # pre-Sprint-27 job's normal connector-driven collection path.
    skip_collection: Mapped[bool] = mapped_column(Boolean, default=False)

    # Sprint 29 (YouTube wizard): both nullable/defaulted so every
    # pre-existing row reads as "no explicit order was requested" / "replies
    # were not collected" -- Retry reuses the same row and never touches
    # these columns, so a job's original choice here is preserved
    # automatically exactly like collection_mode already is.
    comment_order: Mapped[CommentOrder | None] = mapped_column(
        Enum(CommentOrder, native_enum=False, length=32, validate_strings=True), nullable=True
    )
    include_replies: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Dataset jobs only: analyze every text row rather than the bounded
    # per-column sample. Never set by a connector-backed source, which has
    # no free-text column budget to raise.
    full_text_analysis: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Sprint 32: optional per-job override of SENTIMENT_MIN_CONFIDENCE. Null
    # means "use the production default". Retry reuses the same row and
    # never touches this column, so a job's original choice here is
    # preserved automatically exactly like collection_mode already is.
    confidence_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Sprint 33: FAST/HYBRID/SMART LLM-escalation mode. FAST is the
    # production default (identical behavior to pre-Sprint-33). Retry
    # reuses the same row and never touches this column, so it is
    # preserved automatically exactly like collection_mode already is.
    sentiment_mode: Mapped[SentimentMode] = mapped_column(
        Enum(SentimentMode, native_enum=False, length=16, validate_strings=True),
        default=SentimentMode.fast,
        server_default="fast",
    )

    requested_comment_limit: Mapped[int] = mapped_column(Integer)

    comments_discovered: Mapped[int] = mapped_column(Integer, default=0)
    comments_collected: Mapped[int] = mapped_column(Integer, default=0)
    comments_available: Mapped[int] = mapped_column(Integer, default=0)
    comments_processed: Mapped[int] = mapped_column(Integer, default=0)
    comments_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    comments_failed: Mapped[int] = mapped_column(Integer, default=0)

    progress_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    stage_progress_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    status_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    collection_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    # Sprint 34: WHY collection_complete became True (or why collection
    # stopped even though it isn't) -- "source_exhausted" (the source
    # returned no further pages, real end of data) vs
    # "account_cap_reached" (requested_comment_limit -- the resolved
    # per-account safety cap for collection_mode="all_available" -- was
    # hit first). Null while collection is still in progress. Exists so
    # "All available" never silently reports a partial count without
    # explaining why it stopped short of the source's public total (see
    # comments_discovered).
    collection_stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_checkpoint: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class AnalysisJobResult(Base):
    __tablename__ = "analysis_job_results"

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    report_json: Mapped[dict] = mapped_column(_JSONVariant)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
