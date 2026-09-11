from app.exceptions.base import AppError


class SentimentLLMConfigurationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=500)
