import uuid

from app.exceptions.base import AppError


class InvalidPasswordPolicyError(AppError):
    def __init__(self, message: str = "Password does not meet the required policy") -> None:
        super().__init__(message, status_code=422)


class EmailAlreadyRegisteredError(AppError):
    def __init__(self, message: str = "Registration could not be completed") -> None:
        super().__init__(message, status_code=409)


class RegistrationDisabledError(AppError):
    def __init__(self, message: str = "Registration is currently disabled") -> None:
        super().__init__(message, status_code=403)


class InvalidCredentialsError(AppError):
    def __init__(self, message: str = "Invalid email or password") -> None:
        super().__init__(message, status_code=401)


class AccountLockedError(AppError):
    def __init__(self, message: str = "Account is temporarily locked") -> None:
        super().__init__(message, status_code=401)


class AccountDisabledError(AppError):
    def __init__(self, message: str = "Account is disabled") -> None:
        super().__init__(message, status_code=403)


class EmailNotVerifiedError(AppError):
    def __init__(self, message: str = "Please verify your email address before logging in") -> None:
        super().__init__(message, status_code=403)


class InvalidRefreshTokenError(AppError):
    def __init__(self, message: str = "Invalid or expired refresh token") -> None:
        super().__init__(message, status_code=401)


class RefreshTokenReusedError(InvalidRefreshTokenError):
    """A refresh token already marked used_at was presented again -- theft/
    replay signal. Distinguished from a plain invalid token purely so callers
    (the auth service) can emit a refresh_token_reused audit event; the HTTP
    response is intentionally identical to any other invalid-refresh-token
    case (401, generic message) to avoid leaking detection state to a caller.
    user_id (when known) lets the caller attribute the audit event without a
    second database lookup.
    """

    def __init__(
        self, message: str = "Invalid or expired refresh token", user_id: uuid.UUID | None = None
    ) -> None:
        super().__init__(message)
        self.user_id = user_id


class InvalidAccessTokenError(AppError):
    def __init__(self, message: str = "Invalid or expired access token") -> None:
        super().__init__(message, status_code=401)


class InsufficientPermissionsError(AppError):
    def __init__(self, message: str = "You do not have permission to perform this action") -> None:
        super().__init__(message, status_code=403)


class RateLimitExceededError(AppError):
    def __init__(
        self,
        message: str = "Too many requests, please try again later",
        retry_after_seconds: int = 60,
    ) -> None:
        super().__init__(message, status_code=429)
        self.retry_after_seconds = retry_after_seconds


class UsageLimitExceededError(AppError):
    def __init__(self, message: str = "Usage limit exceeded") -> None:
        super().__init__(message, status_code=429)


class InvalidSecurityTokenError(AppError):
    def __init__(self, message: str = "Invalid or expired token") -> None:
        super().__init__(message, status_code=400)


class RateLimitBackendUnavailableError(AppError):
    def __init__(self, message: str = "Rate limiting service is temporarily unavailable") -> None:
        super().__init__(message, status_code=503)


class UserNotFoundError(AppError):
    def __init__(self, message: str = "User not found") -> None:
        super().__init__(message, status_code=404)


class SessionNotFoundError(AppError):
    def __init__(self, message: str = "Session not found") -> None:
        super().__init__(message, status_code=404)


class SelfDemotionNotAllowedError(AppError):
    def __init__(
        self, message: str = "Admins cannot change their own role or disable their own account"
    ) -> None:
        super().__init__(message, status_code=403)


class DisplayNameCooldownActiveError(AppError):
    def __init__(self, days_remaining: int) -> None:
        super().__init__(
            f"You can change your name again in {days_remaining} day"
            f"{'s' if days_remaining != 1 else ''}",
            status_code=422,
        )
        self.days_remaining = days_remaining


class IncorrectPasswordError(AppError):
    def __init__(self, message: str = "Incorrect password") -> None:
        super().__init__(message, status_code=401)
