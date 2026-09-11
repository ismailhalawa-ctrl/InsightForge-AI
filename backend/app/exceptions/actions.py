from app.exceptions.base import AppError


class ActionCenterDisabledError(AppError):
    def __init__(self, message: str = "The Action Center is not enabled") -> None:
        super().__init__(message, status_code=422)


class ActionPlanNotFoundError(AppError):
    def __init__(self, message: str = "Action plan not found") -> None:
        super().__init__(message, status_code=404)


class ActionTaskNotFoundError(AppError):
    def __init__(self, message: str = "Action task not found") -> None:
        super().__init__(message, status_code=404)


class ActionPlanVersionConflictError(AppError):
    def __init__(
        self, message: str = "Action plan was modified by another request -- reload and retry"
    ) -> None:
        super().__init__(message, status_code=409)


class InvalidActionPlanTransitionError(AppError):
    def __init__(self, message: str = "Invalid action plan status transition") -> None:
        super().__init__(message, status_code=409)


class InvalidActionTaskTransitionError(AppError):
    def __init__(self, message: str = "Invalid action task status transition") -> None:
        super().__init__(message, status_code=409)


class ActionPlanTasksIncompleteError(AppError):
    def __init__(
        self,
        message: str = ("All non-cancelled tasks must be done before this plan can be completed"),
    ) -> None:
        super().__init__(message, status_code=409)


class InvalidActionPlanConfigurationError(AppError):
    def __init__(self, message: str = "Invalid action plan configuration") -> None:
        super().__init__(message, status_code=422)


class InvalidActionTaskConfigurationError(AppError):
    def __init__(self, message: str = "Invalid action task configuration") -> None:
        super().__init__(message, status_code=422)


class InvalidSignalForActionPlanError(AppError):
    def __init__(
        self, message: str = "This signal cannot be converted into an action plan"
    ) -> None:
        super().__init__(message, status_code=422)
