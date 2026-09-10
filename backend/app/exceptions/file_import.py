from app.exceptions.base import AppError


class ImportDisabledError(AppError):
    def __init__(self, message: str = "File import is currently disabled") -> None:
        super().__init__(message, status_code=403)


class ImportNotFoundError(AppError):
    def __init__(self, message: str = "Import not found") -> None:
        super().__init__(message, status_code=404)


class ImportStateConflictError(AppError):
    def __init__(self, message: str = "Import is not in a valid state for this action") -> None:
        super().__init__(message, status_code=409)


class UnsupportedImportFormatError(AppError):
    def __init__(self, message: str = "This file format is not supported") -> None:
        super().__init__(message, status_code=400)


class InvalidImportFileError(AppError):
    def __init__(self, message: str = "The uploaded file could not be read") -> None:
        super().__init__(message, status_code=400)


class ImportTooLargeError(AppError):
    def __init__(self, message: str = "The uploaded file exceeds the maximum allowed size") -> None:
        super().__init__(message, status_code=413)


class ImportProfileError(AppError):
    def __init__(self, message: str = "The file could not be profiled") -> None:
        super().__init__(message, status_code=422)


class InvalidColumnMappingError(AppError):
    def __init__(self, message: str = "Invalid column mapping") -> None:
        super().__init__(message, status_code=422)


class ImportStorageError(AppError):
    def __init__(
        self, message: str = "The import storage backend is temporarily unavailable"
    ) -> None:
        super().__init__(message, status_code=503)


class ImportExpiredError(AppError):
    def __init__(
        self, message: str = "This import has expired and its file is no longer available"
    ) -> None:
        super().__init__(message, status_code=410)


class ImportRowLimitError(AppError):
    def __init__(
        self, message: str = "The file exceeds the maximum allowed number of rows"
    ) -> None:
        super().__init__(message, status_code=422)


class ImportProcessingError(AppError):
    def __init__(self, message: str = "Failed to process the import") -> None:
        super().__init__(message, status_code=502)
