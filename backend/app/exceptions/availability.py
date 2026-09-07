from app.exceptions.base import AppError


class DatabaseUnavailableError(AppError):
    def __init__(self, message: str = "The database is temporarily unavailable") -> None:
        super().__init__(message, status_code=503)
