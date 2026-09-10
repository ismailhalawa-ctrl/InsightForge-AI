from app.exceptions.base import AppError


class ReportsDisabledError(AppError):
    def __init__(self, message: str = "Reports are not enabled") -> None:
        super().__init__(message, status_code=422)


class ReportNotFoundError(AppError):
    def __init__(self, message: str = "Report not found") -> None:
        super().__init__(message, status_code=404)


class InvalidReportConfigurationError(AppError):
    def __init__(self, message: str = "Invalid report configuration") -> None:
        super().__init__(message, status_code=422)


class ReportScopeIneligibleError(AppError):
    """Raised when the requested scope exists and is owned by the caller,
    but does not satisfy this report type's own requirements -- e.g. a
    `github_repository_health` report against a non-GitHub dataset, or a
    `release_impact` report against a scope with no completed comparison.
    A client-correctable 400, never a 409: the request itself does not
    satisfy the rules, not a conflict with existing server state.
    """

    def __init__(self, message: str = "This scope is not eligible for this report type") -> None:
        super().__init__(message, status_code=400)


class ReportConflictError(AppError):
    def __init__(
        self, message: str = "This idempotency key was already used for a different report request"
    ) -> None:
        super().__init__(message, status_code=409)
