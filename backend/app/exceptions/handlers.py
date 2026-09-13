import logging
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions.auth import InvalidAccessTokenError, RateLimitExceededError
from app.exceptions.base import AppError

logger = logging.getLogger(__name__)


def _error_response(
    status_code: int, message: str, details: Any = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    error: dict[str, Any] = {"code": status_code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    headers = None
    if isinstance(exc, RateLimitExceededError):
        headers = {"Retry-After": str(exc.retry_after_seconds)}
    elif isinstance(exc, InvalidAccessTokenError):
        # Missing/invalid/expired bearer token on a protected route -- RFC 7235
        # requires WWW-Authenticate on 401 responses that challenge for auth.
        headers = {"WWW-Authenticate": "Bearer"}
    return _error_response(exc.status_code, exc.message, headers=headers)


def _jsonable_validation_errors(errors: list[dict]) -> list[dict]:
    """Makes Pydantic's error list safe to serialise.

    A validator that raises ValueError (the documented way to express a
    cross-field rule in a `model_validator`) puts the exception OBJECT itself
    into the error's `ctx`, which json.dumps cannot encode -- the 422 then
    fails while being rendered and surfaces as a 500. Only `ctx` is
    rewritten, and only into `str`, so the response shape callers already
    parse (`type`, `loc`, `msg`, `input`) is untouched.

    `input` is dropped rather than echoed: it is the caller's own submitted
    value, and a validation failure is not a reason to reflect a field that
    might hold a credential back out in an error body.
    """
    sanitised: list[dict] = []
    for error in errors:
        cleaned = {key: value for key, value in error.items() if key not in ("ctx", "input")}
        if "ctx" in error:
            cleaned["ctx"] = {key: str(value) for key, value in (error["ctx"] or {}).items()}
        sanitised.append(cleaned)
    return sanitised


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Validation error",
        _jsonable_validation_errors(exc.errors()),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _error_response(exc.status_code, str(exc.detail))


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_exception", exc_info=exc)
    return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error")
