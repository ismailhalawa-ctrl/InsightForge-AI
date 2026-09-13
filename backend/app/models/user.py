import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import UserRole, UserStatus

# Deterministic id for the system user that owns pre-Sprint-13 (legacy) rows
# after backfill. Fixed so the Alembic migration and application code agree
# on the same identity without a lookup. Never used for a real registered user.
LEGACY_SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
LEGACY_SYSTEM_USER_EMAIL = "system+legacy@internal.insightforge"

# Sentinel password hash that argon2 can never successfully verify against
# (not a valid encoded hash), guaranteeing the system user can never log in
# with any password. Mirrors Django's well-known "unusable password" pattern.
UNUSABLE_PASSWORD_HASH = "!unusable"


def normalize_email(email: str) -> str:
    """Deterministic normalization applied before every uniqueness check and
    lookup: trims whitespace and lowercases. Applied once, consistently, so
    'User@Example.com' and 'user@example.com ' are always the same account.
    """
    return email.strip().lower()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Nullable with no server_default -- genuinely absent for every user
    # until they change their name for the first time via PATCH /auth/me.
    display_name_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=16, validate_strings=True),
        default=UserRole.user,
        index=True,
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, native_enum=False, length=16, validate_strings=True),
        default=UserStatus.active,
        index=True,
    )

    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)

    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Deterministic internal identity used to own pre-Sprint-13 (legacy) data.
    # System users can never authenticate (see AuthenticationService.login) and
    # are excluded from the admin user listing endpoint.
    is_system_user: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
