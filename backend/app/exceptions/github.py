from datetime import datetime

from app.exceptions.base import AppError
from app.exceptions.source import SourceQuotaExhaustedError


class GitHubConnectorDisabledError(AppError):
    def __init__(self, message: str = "The GitHub connector is not enabled") -> None:
        super().__init__(message, status_code=422)


class GitHubInvalidReferenceError(AppError):
    def __init__(self, message: str = "Invalid GitHub repository reference") -> None:
        super().__init__(message, status_code=422)


class GitHubRepositoryNotFoundError(AppError):
    def __init__(self, message: str = "Repository not found or not accessible") -> None:
        super().__init__(message, status_code=404)


class GitHubPermissionError(AppError):
    def __init__(self, message: str = "GitHub denied access to this repository") -> None:
        super().__init__(message, status_code=403)


class GitHubAuthError(AppError):
    def __init__(self, message: str = "GitHub rejected the provided credentials") -> None:
        super().__init__(message, status_code=502)


class GitHubRateLimitError(SourceQuotaExhaustedError):
    """GitHub's PRIMARY hourly quota is exhausted (`X-RateLimit-Remaining: 0`).

    Carries the reset instant GitHub reported so the job runner can wait out
    the real window rather than exhausting its retry ladder inside it -- see
    SourceQuotaExhaustedError for why that has to be a generic concept and
    not a GitHub-specific branch in the runner.
    """

    def __init__(
        self,
        message: str = "GitHub API rate limit exceeded",
        retry_at: datetime | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message, retry_at=retry_at, retry_after_seconds=retry_after_seconds)


class GitHubAbuseRateLimitError(SourceQuotaExhaustedError):
    """GitHub's SECONDARY (abuse/burst) rate limit, which is independent of
    the primary hourly quota and is signalled with `Retry-After` rather than
    `X-RateLimit-Reset`. Same wait-and-resume treatment, usually for seconds
    to minutes instead of up to an hour.
    """

    def __init__(
        self,
        message: str = "GitHub secondary rate limit triggered",
        retry_at: datetime | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message, retry_at=retry_at, retry_after_seconds=retry_after_seconds)


class GitHubTimeoutError(AppError):
    def __init__(self, message: str = "GitHub API request timed out") -> None:
        super().__init__(message, status_code=504)


class GitHubServiceError(AppError):
    def __init__(self, message: str = "GitHub API is temporarily unavailable") -> None:
        super().__init__(message, status_code=503)


class GitHubPaginationLimitError(GitHubServiceError):
    """GitHub refuses to paginate any further into this listing.

    The REST list endpoints will not serve results past roughly the first
    10,000 items; asking for the page after that comes back as HTTP 422.

    This is a BOUNDARY, not an outage, and the distinction matters a great
    deal: classified as a service error it was retried three times and then
    failed the whole job. Two real runs died exactly this way -- both stuck
    at `page: 100` in the `issues` phase with `done: []`, meaning pull
    requests, comments, reviews, releases and repository documents had never
    been collected at all.

    Subclasses GitHubServiceError so any caller that does not care about the
    distinction keeps its existing behaviour.
    """

    def __init__(
        self, message: str = "GitHub will not paginate further into this listing"
    ) -> None:
        super().__init__(message)


class GitHubAnalysisRequestNotFoundError(AppError):
    def __init__(self, message: str = "GitHub analysis request not found") -> None:
        super().__init__(message, status_code=404)


class GitHubConnectionNotFoundError(AppError):
    def __init__(self, message: str = "GitHub connection not found") -> None:
        super().__init__(message, status_code=404)


class GitHubPrivateRepositoryAccessError(AppError):
    """A repository that either does not exist or is private and not visible
    with the credential used. Deliberately one error for both cases: telling
    an unauthenticated caller "this exists but you can't see it" is exactly
    the private-repository existence leak GitHub itself avoids by returning
    404, and InsightForge must not undo that.
    """

    def __init__(
        self,
        message: str = (
            "Repository not found, or it is private and the selected GitHub "
            "connection does not have access to it"
        ),
    ) -> None:
        super().__init__(message, status_code=404)
