from datetime import UTC, datetime

from app.exceptions.base import AppError


class UnsupportedSourceError(AppError):
    def __init__(self, message: str = "This source type is not supported") -> None:
        super().__init__(message, status_code=422)


class SourceValidationError(AppError):
    def __init__(self, message: str = "Invalid source reference") -> None:
        super().__init__(message, status_code=422)


class SourceUnavailableError(AppError):
    def __init__(self, message: str = "The source is temporarily unavailable") -> None:
        super().__init__(message, status_code=503)


class SourceAuthenticationError(AppError):
    def __init__(self, message: str = "The source rejected the request") -> None:
        super().__init__(message, status_code=502)


class SourceRateLimitError(AppError):
    def __init__(self, message: str = "The source's rate limit was exceeded") -> None:
        super().__init__(message, status_code=429)


class SourceCollectionError(AppError):
    def __init__(self, message: str = "Failed to collect from the source") -> None:
        super().__init__(message, status_code=502)


class SourceCheckpointError(AppError):
    def __init__(self, message: str = "Failed to persist collection checkpoint") -> None:
        super().__init__(message, status_code=500)


class SourceRecordPersistenceError(AppError):
    def __init__(self, message: str = "Failed to persist collected records") -> None:
        super().__init__(message, status_code=500)


class SourceDatasetNotFoundError(AppError):
    def __init__(self, message: str = "Dataset not found") -> None:
        super().__init__(message, status_code=404)


class SourceDatasetInUseError(AppError):
    def __init__(
        self, message: str = "This dataset cannot be deleted while an active job references it"
    ) -> None:
        super().__init__(message, status_code=409)


class SourceInputTooLongError(AppError):
    def __init__(self, message: str = "Input exceeds the maximum allowed length") -> None:
        super().__init__(message, status_code=422)


class DatasetExportTooLargeError(AppError):
    """XLSX export of a dataset too large to build in memory.

    CSV streams and has no equivalent limit, so the message names it as the
    way to get the same data rather than leaving the user stuck.
    """

    def __init__(self, record_count: int, maximum: int) -> None:
        super().__init__(
            f"This dataset has {record_count:,} records, which is too many for an XLSX "
            f"export (limit {maximum:,}). Export as CSV instead -- it is streamed and "
            "has no record limit.",
            status_code=413,
        )


class SourceQuotaExhaustedError(SourceRateLimitError):
    """The source's own quota is exhausted AND the source told us when it
    resets (GitHub's `X-RateLimit-Reset` / `Retry-After`).

    Deliberately generic and deliberately a subclass of SourceRateLimitError:
    a connector that raises this still classifies as an ordinary retryable
    rate-limit error everywhere that doesn't know about the reset time, so
    nothing that already handles SourceRateLimitError changes behavior. What
    the extra `retry_at` buys is the one thing exponential backoff cannot
    express -- "come back at this wall-clock instant" -- which is what
    AnalysisJobRunner._handle_failure uses to wait out a real quota window
    instead of burning every remaining attempt inside it (GitHub's primary
    limit resets on a full hour; the retry ladder tops out at five minutes).

    Only connectors whose source publishes a reset time raise this. YouTube
    never does, so its retry behavior is untouched.
    """

    def __init__(
        self,
        message: str = "The source's rate limit was exceeded",
        retry_at: datetime | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_at = retry_at
        self.retry_after_seconds = retry_after_seconds

    def seconds_until_retry(self, now: datetime | None = None) -> int | None:
        """Seconds to wait, or None when the source gave us nothing to go on
        (the caller then falls back to its ordinary backoff ladder). Never
        negative -- an already-elapsed reset time means "retry now".
        """
        if self.retry_after_seconds is not None:
            return max(0, self.retry_after_seconds)
        if self.retry_at is None:
            return None
        reference = now or datetime.now(UTC)
        return max(0, int((self.retry_at - reference).total_seconds()))
