from app.exceptions.base import AppError


class SignalNotFoundError(AppError):
    def __init__(self, message: str = "Signal not found") -> None:
        super().__init__(message, status_code=404)


class SignalConfigurationError(AppError):
    def __init__(self, message: str = "Invalid signal intelligence configuration") -> None:
        super().__init__(message, status_code=500)


class SignalGenerationError(AppError):
    def __init__(self, message: str = "Failed to generate signals") -> None:
        super().__init__(message, status_code=500)
