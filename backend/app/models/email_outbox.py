import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import EmailOutboxStatus, EmailTemplate

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class EmailOutboxEntry(Base):
    """A queued transactional email. Created in the same database
    transaction as the security token/event that triggers it where
    practical, so a delivery failure never undoes an already-completed
    token consumption, password reset, or email verification. Dispatched by
    a dedicated email worker (python -m app.workers.email_worker), never by
    the analysis worker or an inline blocking SMTP call from a request.
    """

    __tablename__ = "email_outbox"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    recipient: Mapped[str] = mapped_column(String(320))
    template: Mapped[EmailTemplate] = mapped_column(
        Enum(EmailTemplate, native_enum=False, length=32, validate_strings=True), index=True
    )
    payload: Mapped[dict] = mapped_column(_JSONVariant, default=dict)

    status: Mapped[EmailOutboxStatus] = mapped_column(
        Enum(EmailOutboxStatus, native_enum=False, length=16, validate_strings=True),
        default=EmailOutboxStatus.pending,
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
