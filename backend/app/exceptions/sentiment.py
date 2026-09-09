from app.exceptions.base import AppError


class SentimentConfigurationError(AppError):
    def __init__(self, message: str = "Invalid sentiment model configuration") -> None:
        super().__init__(message, status_code=500)


class SentimentModelLoadError(AppError):
    def __init__(self, message: str = "Failed to load sentiment model") -> None:
        super().__init__(message, status_code=500)


class SentimentDeviceError(AppError):
    def __init__(self, message: str = "Requested inference device is unavailable") -> None:
        super().__init__(message, status_code=500)


class SentimentInferenceError(AppError):
    def __init__(self, message: str = "Sentiment inference failed") -> None:
        super().__init__(message, status_code=500)


class AnalysisServiceUnavailableError(AppError):
    def __init__(
        self, message: str = "The sentiment analysis service is temporarily unavailable"
    ) -> None:
        super().__init__(message, status_code=503)
