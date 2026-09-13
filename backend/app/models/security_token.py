import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import SecurityTokenPurpose

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class UserSecurityToken(Base):
    """A single-use, expiring, opaque token for a purpose-bound security
    action (email verification, password reset). The raw token is never
    persisted -- only a SHA-256 hash of (token + pepper), mirroring
    RefreshSession.token_hash. Issuing a replacement token for the same
    user/purpose revokes every prior active token for that pair.
    """

    __tablename__ = "user_security_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    purpose: Mapped[SecurityTokenPurpose] = mapped_column(
        Enum(SecurityTokenPurpose, native_enum=False, length=32, validate_strings=True), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_metadata: Mapped[dict] = mapped_column(_JSONVariant, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
