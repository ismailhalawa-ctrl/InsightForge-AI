import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class RefreshSession(Base):
    """A single refresh-token issuance, part of a rotation family.

    The raw refresh token is never persisted -- only a SHA-256 hash of
    (token + AUTH_REFRESH_TOKEN_PEPPER). family_id groups every token that
    descends from the same original login: rotating a token creates a new row
    in the same family and marks the old row used_at/replaced_by_token_id.
    Presenting an already-used token again indicates theft/replay and revokes
    every row in the family (see RefreshTokenService.rotate).
    """

    __tablename__ = "refresh_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    parent_token_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("refresh_sessions.id", ondelete="SET NULL"), nullable=True
    )
    replaced_by_token_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("refresh_sessions.id", ondelete="SET NULL"), nullable=True
    )

    # Bounded/hashed only -- raw IP/user-agent values are never stored (see
    # README "Session fingerprints"). HMAC-SHA256 hex digest (pepper-keyed),
    # or NULL when unavailable. Informational/anomaly metadata only -- never
    # used as a sole authentication factor, and a change never auto-locks
    # the session.
    created_by_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_used_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
