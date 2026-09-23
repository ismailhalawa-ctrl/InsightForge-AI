import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import AssistantMessageRole, AssistantScopeType, SourceType

# Real JSONB on PostgreSQL; plain JSON on any other dialect (SQLite in fast
# offline unit tests) -- same pattern as app/models/analysis_job.py.
_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class AssistantSession(Base):
    """One persisted global-assistant conversation. Global means source-
    agnostic by construction: a session's scope narrows retrieval to
    all-of-the-user's-analyses / one source type / one specific job, never
    hardcoded to YouTube. Scope is fixed at creation time (see
    app/services/assistant/service.py) -- changing scope mid-conversation
    always starts a new session, so a conversation's evidence context is
    never ambiguous."""

    __tablename__ = "assistant_sessions"
    __table_args__ = (
        Index("ix_assistant_sessions_user_id_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Set from the first question (truncated), same convention as
    # SentimentPro's audience assistant. Null until the first message.
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)

    scope_type: Mapped[AssistantScopeType] = mapped_column(
        Enum(AssistantScopeType, native_enum=False, length=16, validate_strings=True)
    )
    # Set only when scope_type == "source".
    scope_source_type: Mapped[SourceType | None] = mapped_column(
        Enum(SourceType, native_enum=False, length=32, validate_strings=True), nullable=True
    )
    # Set only when scope_type == "job". ON DELETE SET NULL (not CASCADE):
    # if the underlying analysis job is ever deleted, the conversation
    # history itself is still worth keeping -- it just loses its live scope
    # target, the same tradeoff app/models/analysis_job.py's own
    # source_dataset_id FK makes.
    scope_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Bumped on every new message (not just edits) so the session list can
    # sort by conversation recency, matching SentimentPro's index intent.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["AssistantMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AssistantMessage.created_at",
    )


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (
        Index("ix_assistant_messages_session_id_created_at", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assistant_sessions.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[AssistantMessageRole] = mapped_column(
        Enum(AssistantMessageRole, native_enum=False, length=16, validate_strings=True)
    )
    content: Mapped[str] = mapped_column(Text)

    # [{job_id, source_type, record_id, record_type, excerpt}, ...]. Always
    # server-hydrated from actually-retrieved tool results -- see
    # app/services/assistant/agent.py -- never trusted verbatim from the
    # LLM's own output.
    citations_json: Mapped[list] = mapped_column(_JSONVariant, default=list)
    # [{tool, status, arguments, result_summary}, ...] -- audit trail of
    # which tools ran to produce this answer, shown in the UI as an
    # expandable "N tools used" indicator (SentimentPro's
    # ToolActivityIndicator pattern).
    tool_calls_json: Mapped[list] = mapped_column(_JSONVariant, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[AssistantSession] = relationship(back_populates="messages")
