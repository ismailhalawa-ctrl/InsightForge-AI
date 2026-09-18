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
from app.models.enums import SignalEvidenceRole, SignalSeverity, SignalType

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")

SIGNAL_TITLE_MAX_CHARS = 255
SIGNAL_SUMMARY_MAX_CHARS = 2000
SIGNAL_STABLE_KEY_MAX_CHARS = 128


class AnalysisSignal(Base):
    """A persisted, structured, explainable signal derived from one job's
    AnalysisRecordEvidence rows (Sprint 17). Distinct from AnalysisJobInsight
    (a cached, on-demand narrative report): a signal is a queryable,
    filterable, individually-linkable row generated automatically once per
    job by AnalysisJobRunner, not regenerated on every API request.

    `stable_key` is a deterministic identifier derived from signal_type plus
    the group's canonical grouping key (see app/services/signals/grouping.py)
    -- NOT a random id -- so a retried job upserts the same signal row
    instead of creating a duplicate. `algorithm_version` records which
    grouping/classification version produced this row, so a future algorithm
    change can coexist with historical signals rather than silently
    reinterpreting them.

    Every numeric/categorical field here is either directly MEASURED from
    evidence (frequency_count, evidence_count, sentiment/language/rating
    distributions inside measured_metrics) or an explicitly-labeled INFERENCE
    (confidence, priority_score, severity) -- never presented as objective
    fact. See README "Structured signal intelligence" for the full
    measured-vs-inferred-vs-recommended distinction this table encodes.
    """

    __tablename__ = "analysis_signals"
    __table_args__ = (
        UniqueConstraint("job_id", "stable_key", name="uq_signal_job_stable_key"),
        Index("ix_signal_job_id", "job_id"),
        Index("ix_signal_job_type", "job_id", "signal_type"),
        Index("ix_signal_job_priority", "job_id", "priority_score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE")
    )
    source_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_datasets.id", ondelete="SET NULL"), nullable=True
    )

    signal_type: Mapped[SignalType] = mapped_column(
        Enum(SignalType, native_enum=False, length=32, validate_strings=True)
    )
    stable_key: Mapped[str] = mapped_column(String(SIGNAL_STABLE_KEY_MAX_CHARS))

    title: Mapped[str] = mapped_column(String(SIGNAL_TITLE_MAX_CHARS))
    summary: Mapped[str] = mapped_column(String(SIGNAL_SUMMARY_MAX_CHARS))

    confidence: Mapped[float] = mapped_column(Float)
    priority_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[SignalSeverity] = mapped_column(
        Enum(SignalSeverity, native_enum=False, length=16, validate_strings=True)
    )

    frequency_count: Mapped[int] = mapped_column(Integer)
    evidence_count: Mapped[int] = mapped_column(Integer)

    first_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    measured_metrics: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    recommended_actions: Mapped[list] = mapped_column(_JSONVariant, default=list)
    limitations: Mapped[list] = mapped_column(_JSONVariant, default=list)

    algorithm_version: Mapped[str] = mapped_column(String(16))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AnalysisSignalEvidence(Base):
    """Junction linking one AnalysisSignal to the AnalysisRecordEvidence rows
    that support (or, for evidence_role='contradicting', complicate) it.
    Every persisted signal has at least one row here -- a signal with no
    linked evidence is never created (see SignalGenerationService)."""

    __tablename__ = "analysis_signal_evidence"
    __table_args__ = (
        UniqueConstraint(
            "signal_id", "analysis_record_evidence_id", name="uq_signal_evidence_pair"
        ),
        Index("ix_signal_evidence_signal_id", "signal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    signal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_signals.id", ondelete="CASCADE")
    )
    analysis_record_evidence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_comment_evidence.id", ondelete="CASCADE")
    )

    relevance_score: Mapped[float] = mapped_column(Float)
    evidence_role: Mapped[SignalEvidenceRole] = mapped_column(
        Enum(SignalEvidenceRole, native_enum=False, length=16, validate_strings=True)
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
