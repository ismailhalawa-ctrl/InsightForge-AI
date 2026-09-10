from app.exceptions.base import AppError


class AskDataDisabledError(AppError):
    def __init__(self, message: str = "Ask Your Data is not enabled") -> None:
        super().__init__(message, status_code=422)


class InvalidQueryConfigurationError(AppError):
    def __init__(self, message: str = "Invalid query request") -> None:
        super().__init__(message, status_code=422)


class UnsupportedQuestionError(AppError):
    """Raised for a question this system cannot ground an answer for --
    never guessed at, never silently answered from general knowledge. The
    API still returns 200 with an `answer_type="unsupported"` payload for
    genuinely ambiguous-but-benign questions (see
    app/services/query/service.py); this exception is reserved for requests
    that are structurally invalid rather than merely unanswerable (e.g. no
    scope at all was provided and none could be inferred).
    """

    def __init__(self, message: str = "This question is not supported") -> None:
        super().__init__(message, status_code=422)
