from app.exceptions.base import AppError


class AnalysisJobNotFoundError(AppError):
    def __init__(self, message: str = "Analysis job not found") -> None:
        super().__init__(message, status_code=404)


class AnalysisJobNotCompletedError(AppError):
    def __init__(self, message: str = "Analysis job has not completed yet") -> None:
        super().__init__(message, status_code=409)


class AnalysisJobAlreadyTerminalError(AppError):
    def __init__(self, message: str = "Analysis job is already in a terminal state") -> None:
        super().__init__(message, status_code=409)


class InvalidJobConfigurationError(AppError):
    def __init__(self, message: str = "Invalid analysis job configuration") -> None:
        super().__init__(message, status_code=422)


class UnsupportedSourceTypeError(AppError):
    def __init__(self, message: str = "Unsupported analysis source type") -> None:
        super().__init__(message, status_code=422)


class AnalysisJobConfigurationError(AppError):
    def __init__(self, message: str = "Invalid analysis worker configuration") -> None:
        super().__init__(message, status_code=500)


class AnalysisJobNotRetryableError(AppError):
    def __init__(self, message: str = "Job cannot be retried in its current state") -> None:
        super().__init__(message, status_code=409)
