from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole, UserStatus


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserSummary(BaseModel):
    """Public-safe user representation -- never includes password_hash or
    any other credential material."""

    id: UUID
    email: str
    display_name: str | None
    display_name_changed_at: datetime | None
    role: UserRole
    status: UserStatus
    is_email_verified: bool
    created_at: datetime
    last_login_at: datetime | None


class UpdateDisplayNameRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class DeleteAccountRequest(BaseModel):
    """Password re-confirmation is a server-side security gate, not just
    client-side UX friction -- an XSS or a stray click on a
    forgotten-logged-in session shouldn't be able to permanently delete an
    account with zero re-authentication."""

    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_token_expires_in_seconds: int
    refresh_token_expires_in_seconds: int
    user: UserSummary


class LogoutResponse(BaseModel):
    message: str = "Logged out"


class LogoutAllResponse(BaseModel):
    message: str = "All sessions revoked"


class GenericMessageResponse(BaseModel):
    message: str


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=1, max_length=256)


class SessionSummary(BaseModel):
    """Safe session representation -- never includes the token hash,
    fingerprints, or rotation lineage."""

    id: UUID
    issued_at: datetime
    expires_at: datetime
    last_used_at: datetime
    is_current: bool
    revoked: bool


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
