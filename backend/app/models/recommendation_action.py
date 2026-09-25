import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import RecommendationActionStatus

RECOMMENDATION_KEY_MAX_CHARS = 255
RECOMMENDATION_TITLE_MAX_CHARS = 300
RECOMMENDATION_ENTITY_KEY_MAX_CHARS = 512


class RecommendationAction(Base):
    """Lightweight status for ONE recommendation of ONE analysis.

    Deliberately not a task or a plan (ActionPlan already exists for that).
    A row is created lazily the first time a user changes a recommendation's
    status; an untouched recommendation has no row and reads as `open`. The
    recommendation itself is never copied here beyond its title -- the
    analysis remains the source of truth for what it says.

    `entity_key` (the URL, repository, file name or video the analysis was
    of) is denormalised at write time so a later analysis of the same
    subject can show what the user did about the same recommendation last
    time, without a live join through the analysis tables.
    """

    __tablename__ = "recommendation_actions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "job_id", "recommendation_key", name="uq_recommendation_action_user_job_key"
        ),
        Index("ix_recommendation_action_user_status", "user_id", "status"),
        Index("ix_recommendation_action_user_entity", "user_id", "entity_key"),
        Index("ix_recommendation_action_job_id", "job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE")
    )
    recommendation_key: Mapped[str] = mapped_column(String(RECOMMENDATION_KEY_MAX_CHARS))
    entity_key: Mapped[str | None] = mapped_column(
        String(RECOMMENDATION_ENTITY_KEY_MAX_CHARS), nullable=True
    )
    title: Mapped[str] = mapped_column(String(RECOMMENDATION_TITLE_MAX_CHARS))
    source: Mapped[str] = mapped_column(String(16), default="deterministic")
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    related_finding_key: Mapped[str | None] = mapped_column(
        String(RECOMMENDATION_KEY_MAX_CHARS), nullable=True
    )
    status: Mapped[RecommendationActionStatus] = mapped_column(
        Enum(RecommendationActionStatus, native_enum=False, length=16, validate_strings=True),
        default=RecommendationActionStatus.open,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
