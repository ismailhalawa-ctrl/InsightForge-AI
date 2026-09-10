from app.exceptions.base import AppError


class TrendIntelligenceDisabledError(AppError):
    def __init__(self, message: str = "Trend intelligence is not enabled") -> None:
        super().__init__(message, status_code=422)


class ComparisonNotFoundError(AppError):
    def __init__(self, message: str = "Comparison not found") -> None:
        super().__init__(message, status_code=404)


class ActionOutcomeNotFoundError(AppError):
    def __init__(self, message: str = "Action outcome not found") -> None:
        super().__init__(message, status_code=404)


class InvalidComparisonConfigurationError(AppError):
    def __init__(self, message: str = "Invalid comparison configuration") -> None:
        super().__init__(message, status_code=422)


class ComparisonEligibilityError(AppError):
    """Raised when a requested comparison (job pair, or job pair plus an
    action plan) fails one of the eligibility rules enforced in
    app/services/trends/service.py before any matching/trend computation
    runs -- e.g. the two jobs belong to different SourceDatasets, one of the
    jobs has not completed, either job has too few analyzable records or no
    signals/evidence, the baseline job is not earlier than the comparison
    job, a before/after event comparison is missing `event_at`, the
    available evidence timestamps cannot support the requested window, or an
    action-plan comparison references a plan/signal/job that does not belong
    together. Always a client-correctable 400, never a 409: nothing about
    server state conflicts here, the request itself does not satisfy the
    rules and resubmitting the same request will fail the same way.
    """

    def __init__(self, message: str = "This comparison is not eligible to be computed") -> None:
        super().__init__(message, status_code=400)


class ComparisonConflictError(AppError):
    def __init__(
        self, message: str = "This comparison conflicts with an existing resource"
    ) -> None:
        super().__init__(message, status_code=409)


class InvalidActionOutcomeRequestError(AppError):
    def __init__(self, message: str = "Invalid action outcome evaluation request") -> None:
        super().__init__(message, status_code=422)
