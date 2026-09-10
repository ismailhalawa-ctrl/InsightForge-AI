from app.exceptions.base import AppError


class BillingNotConfiguredError(AppError):
    def __init__(self, message: str = "Billing is not configured on this server") -> None:
        super().__init__(message, status_code=503)


class NoActiveSubscriptionError(AppError):
    def __init__(self, message: str = "No active subscription to manage") -> None:
        super().__init__(message, status_code=404)
