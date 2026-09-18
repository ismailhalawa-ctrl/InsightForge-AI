import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
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
    ActionPlanEventType,
    ActionPlanPriority,
    ActionPlanStatus,
    ActionTaskStatus,
    SignalType,
)

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")

ACTION_PLAN_TITLE_MAX_CHARS = 255
ACTION_PLAN_DESCRIPTION_MAX_CHARS = 4000
ACTION_PLAN_OWNER_LABEL_MAX_CHARS = 255
ACTION_PLAN_SUCCESS_METRIC_MAX_CHARS = 500
ACTION_PLAN_EXPECTED_OUTCOME_MAX_CHARS = 1000
ACTION_PLAN_IDEMPOTENCY_KEY_MAX_CHARS = 255

ACTION_TASK_TITLE_MAX_CHARS = 255
ACTION_TASK_DESCRIPTION_MAX_CHARS = 2000


class ActionPlan(Base):
    """A user-owned, trackable plan of action -- created manually or from one
    AnalysisSignal (Sprint 19). Deliberately copies only bounded fields
    (title/description/priority/recommendations) from its source signal at
    creation time rather than reading through a live join: `source_signal_id`
    and `source_job_id` are ON DELETE SET NULL, so this plan's own content
    stays fully readable even after the originating signal or job is gone.

    `version` supports optimistic concurrency: every mutating update is an
    atomic `UPDATE ... WHERE id = :id AND version = :expected_version`
    (see ActionPlanRepository.update_with_version) -- a stale caller's write
    is rejected with a 409, never silently overwritten or silently lost.

    This table is pure internal record-keeping: no field here ever triggers
    an external action (no webhook, no issue tracker sync, no notification).
    """

    __tablename__ = "action_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_action_plan_user_idempotency_key"),
        Index("ix_action_plan_user_id", "user_id"),
        Index("ix_action_plan_user_status", "user_id", "status"),
        Index("ix_action_plan_user_priority", "user_id", "priority"),
        Index("ix_action_plan_due_at", "due_at"),
        Index("ix_action_plan_source_signal_id", "source_signal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # No index=True here -- ix_action_plan_user_id (below, in __table_args__)
    # already covers this column; a second, redundant auto-named index would
    # only add write overhead with no query benefit.
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )

    source_signal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_signals.id", ondelete="SET NULL"), nullable=True
    )
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalized from the source signal at creation time (never re-read via
    # a live join) so "filter plans by source signal type" keeps working
    # after the signal itself is gone -- same rationale as copying title/
    # summary/priority instead of referencing them live.
    source_signal_type: Mapped[SignalType | None] = mapped_column(
        Enum(SignalType, native_enum=False, length=32, validate_strings=True), nullable=True
    )

    title: Mapped[str] = mapped_column(String(ACTION_PLAN_TITLE_MAX_CHARS))
    description: Mapped[str] = mapped_column(String(ACTION_PLAN_DESCRIPTION_MAX_CHARS))
    status: Mapped[ActionPlanStatus] = mapped_column(
        Enum(ActionPlanStatus, native_enum=False, length=16, validate_strings=True),
        default=ActionPlanStatus.draft,
    )
    priority: Mapped[ActionPlanPriority] = mapped_column(
        Enum(ActionPlanPriority, native_enum=False, length=16, validate_strings=True),
        default=ActionPlanPriority.medium,
    )

    owner_label: Mapped[str | None] = mapped_column(
        String(ACTION_PLAN_OWNER_LABEL_MAX_CHARS), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    success_metric: Mapped[str | None] = mapped_column(
        String(ACTION_PLAN_SUCCESS_METRIC_MAX_CHARS), nullable=True
    )
    expected_outcome: Mapped[str | None] = mapped_column(
        String(ACTION_PLAN_EXPECTED_OUTCOME_MAX_CHARS), nullable=True
    )

    # User-scoped idempotency (see the unique constraint above): the same
    # user submitting the same Idempotency-Key twice always resolves to the
    # same plan, but two different users may each safely use "1", "retry-1",
    # etc. without colliding with each other.
    idempotency_key: Mapped[str | None] = mapped_column(
        String(ACTION_PLAN_IDEMPOTENCY_KEY_MAX_CHARS), nullable=True
    )

    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActionTask(Base):
    """One step within an ActionPlan. `position` is a plain ordering integer
    (not necessarily contiguous -- deleting a task leaves a gap, which is
    harmless since ordering only ever reads `ORDER BY position`); the
    dedicated /reorder endpoint is the only path that reassigns positions in
    bulk, keeping position-uniqueness handling in one place rather than
    scattered across individual task edits.
    """

    __tablename__ = "action_tasks"
    __table_args__ = (
        UniqueConstraint("action_plan_id", "position", name="uq_action_task_plan_position"),
        Index("ix_action_task_plan_id", "action_plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("action_plans.id", ondelete="CASCADE")
    )

    title: Mapped[str] = mapped_column(String(ACTION_TASK_TITLE_MAX_CHARS))
    description: Mapped[str | None] = mapped_column(
        String(ACTION_TASK_DESCRIPTION_MAX_CHARS), nullable=True
    )
    status: Mapped[ActionTaskStatus] = mapped_column(
        Enum(ActionTaskStatus, native_enum=False, length=16, validate_strings=True),
        default=ActionTaskStatus.todo,
    )
    position: Mapped[int] = mapped_column(Integer)

    owner_label: Mapped[str | None] = mapped_column(
        String(ACTION_PLAN_OWNER_LABEL_MAX_CHARS), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Index into the source signal's recommended_actions list at the time
    # this task was generated -- traceability without duplicating the full
    # recommendation payload onto every task.
    source_recommendation_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ActionPlanEvent(Base):
    """Append-only audit trail for one ActionPlan. `previous_values`/
    `new_values` hold only the specific bounded fields that changed (see
    app/services/actions/service.py's `_bounded_event_values`) -- never a
    full snapshot, never raw evidence text, never a secret. A row with an
    unknown/deleted actor (`actor_user_id` is ON DELETE SET NULL) still
    keeps its event_type and value diff, so history survives account
    deletion even though the identity of who did it does not.
    """

    __tablename__ = "action_plan_events"
    __table_args__ = (Index("ix_action_plan_event_plan_id", "action_plan_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("action_plans.id", ondelete="CASCADE")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    event_type: Mapped[ActionPlanEventType] = mapped_column(
        Enum(ActionPlanEventType, native_enum=False, length=32, validate_strings=True)
    )
    previous_values: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    new_values: Mapped[dict] = mapped_column(_JSONVariant, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
