import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import (
    ActionOutcomeResult,
    ComparisonStatus,
    ComparisonType,
    SignalTrendDirection,
    SignalType,
)

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")

COMPARISON_TITLE_MAX_CHARS = 255
COMPARISON_EVENT_NAME_MAX_CHARS = 255
COMPARISON_IDEMPOTENCY_KEY_MAX_CHARS = 255
TREND_STABLE_MATCH_KEY_MAX_CHARS = 128
TREND_TITLE_MAX_CHARS = 255


class AnalysisComparison(Base):
    """A user-requested, longitudinal comparison of two completed
    AnalysisJobs from the same SourceDataset (Sprint 20). Never re-collects
    from the source and never reruns Text Intelligence/sentiment -- it only
    reads the two jobs' already-persisted AnalysisSignal/AnalysisRecordEvidence
    rows (see app/services/trends/service.py). `summary`/`limitations` hold
    only bounded, code-computed (and optionally AI-narrated, never AI-scored)
    JSON -- never raw evidence text, never an author identity.

    `idempotency_key` is unique per (user_id, idempotency_key), the same
    user-scoped convention ActionPlan uses -- a NULL key never collides with
    another NULL (Postgres treats NULLs as distinct in the constraint), so
    only a genuinely repeated (user, key) pair is ever rejected.
    """

    __tablename__ = "analysis_comparisons"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_comparison_user_idempotency_key"),
        Index("ix_comparison_user_id", "user_id"),
        Index("ix_comparison_source_dataset_id", "source_dataset_id"),
        Index("ix_comparison_baseline_job_id", "baseline_job_id"),
        Index("ix_comparison_comparison_job_id", "comparison_job_id"),
        Index("ix_comparison_type", "comparison_type"),
        Index("ix_comparison_action_plan_id", "action_plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    source_dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_datasets.id", ondelete="CASCADE")
    )
    baseline_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE")
    )
    comparison_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE")
    )
    action_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("action_plans.id", ondelete="SET NULL"), nullable=True
    )

    comparison_type: Mapped[ComparisonType] = mapped_column(
        Enum(ComparisonType, native_enum=False, length=32, validate_strings=True)
    )
    title: Mapped[str] = mapped_column(String(COMPARISON_TITLE_MAX_CHARS))

    event_name: Mapped[str | None] = mapped_column(
        String(COMPARISON_EVENT_NAME_MAX_CHARS), nullable=True
    )
    event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Persisted (not just request-time parameters) so a replayed/idempotent
    # request and GET /{id} both reproduce the exact window this comparison
    # was actually computed with.
    window_before_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window_after_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[ComparisonStatus] = mapped_column(
        Enum(ComparisonStatus, native_enum=False, length=16, validate_strings=True),
        default=ComparisonStatus.pending,
    )
    summary: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    limitations: Mapped[list] = mapped_column(_JSONVariant, default=list)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    algorithm_version: Mapped[str] = mapped_column(String(16))

    idempotency_key: Mapped[str | None] = mapped_column(
        String(COMPARISON_IDEMPOTENCY_KEY_MAX_CHARS), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignalTrend(Base):
    """One matched (or unmatched-new/unmatched-resolved) signal pair within
    one AnalysisComparison. `stable_match_key` is always the ORIGINATING
    signal's own `stable_key` (baseline's if matched or resolved,
    comparison's if new) -- unique per comparison because a signal is never
    matched more than once within the same comparison (see
    app/services/trends/matching.py's bipartite assignment).

    `baseline_signal_id`/`comparison_signal_id` are ON DELETE SET NULL, not
    CASCADE: the measured counts/trend classification here are this row's
    own frozen-at-computation-time values, not a live read-through -- a
    trend row stays fully readable and meaningful even if the underlying
    AnalysisSignal is later regenerated or removed.
    """

    __tablename__ = "signal_trends"
    __table_args__ = (
        UniqueConstraint(
            "comparison_id", "stable_match_key", name="uq_signal_trend_comparison_key"
        ),
        Index("ix_signal_trend_comparison_id", "comparison_id"),
        Index("ix_signal_trend_trend", "comparison_id", "trend"),
        Index("ix_signal_trend_signal_type", "comparison_id", "signal_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_comparisons.id", ondelete="CASCADE")
    )
    baseline_signal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_signals.id", ondelete="SET NULL"), nullable=True
    )
    comparison_signal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_signals.id", ondelete="SET NULL"), nullable=True
    )

    signal_type: Mapped[SignalType] = mapped_column(
        Enum(SignalType, native_enum=False, length=32, validate_strings=True)
    )
    stable_match_key: Mapped[str] = mapped_column(String(TREND_STABLE_MATCH_KEY_MAX_CHARS))
    title: Mapped[str] = mapped_column(String(TREND_TITLE_MAX_CHARS))

    trend: Mapped[SignalTrendDirection] = mapped_column(
        Enum(SignalTrendDirection, native_enum=False, length=32, validate_strings=True)
    )

    baseline_count: Mapped[int] = mapped_column(Integer, default=0)
    comparison_count: Mapped[int] = mapped_column(Integer, default=0)
    absolute_change: Mapped[int] = mapped_column(Integer, default=0)
    percentage_change: Mapped[float | None] = mapped_column(Float, nullable=True)

    baseline_priority: Mapped[float | None] = mapped_column(Float, nullable=True)
    comparison_priority: Mapped[float | None] = mapped_column(Float, nullable=True)

    match_confidence: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)

    measured_metrics: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    limitations: Mapped[list] = mapped_column(_JSONVariant, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActionOutcome(Base):
    """The measured, non-causal effect of one ActionPlan, evaluated against
    one AnalysisComparison (Sprint 20). Never modifies the plan itself --
    `interpretation` carries only a *suggested* next status; the plan's own
    `status` field remains entirely user-controlled (see
    app/services/trends/outcomes.py and README "Action outcomes").
    """

    __tablename__ = "action_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "action_plan_id", "comparison_id", name="uq_action_outcome_plan_comparison"
        ),
        Index("ix_action_outcome_action_plan_id", "action_plan_id"),
        Index("ix_action_outcome_comparison_id", "comparison_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("action_plans.id", ondelete="CASCADE")
    )
    comparison_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_comparisons.id", ondelete="CASCADE")
    )

    outcome: Mapped[ActionOutcomeResult] = mapped_column(
        Enum(ActionOutcomeResult, native_enum=False, length=16, validate_strings=True)
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    measured_results: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    interpretation: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    limitations: Mapped[list] = mapped_column(_JSONVariant, default=list)

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
