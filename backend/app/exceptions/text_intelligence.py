from app.exceptions.base import AppError


class TextIntelligenceConfigurationError(AppError):
    def __init__(self, message: str = "Invalid text intelligence configuration") -> None:
        super().__init__(message, status_code=500)
