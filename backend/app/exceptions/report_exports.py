from app.exceptions.base import AppError


class ReportExportNotFoundError(AppError):
    def __init__(self, message: str = "Report export not found") -> None:
        super().__init__(message, status_code=404)


class ReportExportNotTabularError(AppError):
    def __init__(
        self,
        message: str = "This report has no tabular data (signals, recommendations, or "
        "evidence) to export as CSV",
    ) -> None:
        super().__init__(message, status_code=422)


class ReportExportTooLargeError(AppError):
    def __init__(
        self, message: str = "The rendered export exceeds the maximum allowed file size"
    ) -> None:
        super().__init__(message, status_code=413)


class ReportExportExpiredError(AppError):
    def __init__(
        self, message: str = "This export has expired and its file is no longer available"
    ) -> None:
        super().__init__(message, status_code=410)


class ReportExportStorageError(AppError):
    def __init__(
        self, message: str = "The report export storage backend is temporarily unavailable"
    ) -> None:
        super().__init__(message, status_code=503)


class ReportExportGenerationError(AppError):
    def __init__(self, message: str = "Failed to generate the export file") -> None:
        super().__init__(message, status_code=502)
