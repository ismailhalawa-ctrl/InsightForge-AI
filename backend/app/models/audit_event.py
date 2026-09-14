import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import AuditEventResult, AuditEventType

# Real JSONB on PostgreSQL; plain JSON on any other dialect (SQLite in fast
# offline unit tests) -- same cross-dialect pattern as AnalysisJob.last_checkpoint.
_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class AuditEvent(Base):
    """Structured security-audit trail. Never stores credentials, tokens, or
    raw request bodies -- only safe, bounded metadata (see AuditLogger)."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Subject of the event (nullable: e.g. a failed login for a nonexistent email).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Who performed the action, when different from user_id (e.g. an admin
    # changing another user's role). NULL when the subject acted on themselves.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    event_type: Mapped[AuditEventType] = mapped_column(
        Enum(AuditEventType, native_enum=False, length=64, validate_strings=True), index=True
    )
    result: Mapped[AuditEventResult] = mapped_column(
        Enum(AuditEventResult, native_enum=False, length=16, validate_strings=True)
    )
    event_metadata: Mapped[dict] = mapped_column(_JSONVariant, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
