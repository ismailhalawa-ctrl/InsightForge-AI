import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.clients.redis_client import check_redis_health, create_redis_client, mask_redis_url
from app.config.settings import get_settings
from app.core.logging import configure_logging
from app.database.session import engine
from app.exceptions.base import AppError
from app.exceptions.handlers import (
    app_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_error_handler,
)
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services.llm.scheduler import configure_scheduler
from app.workers.embedded import start_embedded_worker, stop_embedded_worker

configure_logging()

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("application_startup", extra={"environment": settings.ENVIRONMENT})
    # One admission gate in front of the local inference endpoint, shared by
    # the Assistant, sentiment escalation and insight discovery. Configured
    # once here so every subsystem in this process agrees on the capacity.
    configure_scheduler(
        settings.LLM_MAX_CONCURRENT_REQUESTS,
        settings.LLM_RESERVED_INTERACTIVE_SLOTS,
    )
    if (
        settings.AUTH_ACCESS_TOKEN_SECRET_AUTO_GENERATED
        or settings.AUTH_REFRESH_TOKEN_PEPPER_AUTO_GENERATED
        or settings.AUTH_SECURITY_TOKEN_PEPPER_AUTO_GENERATED
        or settings.RATE_LIMIT_IDENTITY_PEPPER_AUTO_GENERATED
        or settings.AUTH_SESSION_FINGERPRINT_PEPPER_AUTO_GENERATED
        or settings.CONNECTOR_CREDENTIAL_ENCRYPTION_KEY_AUTO_GENERATED
    ):
        logger.warning(
            "auth_secret_auto_generated_development_only",
            extra={
                "access_token_secret_auto_generated": settings.AUTH_ACCESS_TOKEN_SECRET_AUTO_GENERATED,
                "refresh_token_pepper_auto_generated": settings.AUTH_REFRESH_TOKEN_PEPPER_AUTO_GENERATED,
                "security_token_pepper_auto_generated": settings.AUTH_SECURITY_TOKEN_PEPPER_AUTO_GENERATED,
                "rate_limit_identity_pepper_auto_generated": settings.RATE_LIMIT_IDENTITY_PEPPER_AUTO_GENERATED,
                "session_fingerprint_pepper_auto_generated": settings.AUTH_SESSION_FINGERPRINT_PEPPER_AUTO_GENERATED,
                "connector_credential_encryption_key_auto_generated": (
                    settings.CONNECTOR_CREDENTIAL_ENCRYPTION_KEY_AUTO_GENERATED
                ),
                "detail": (
                    "One or more auth secrets/peppers were not configured -- using an "
                    "ephemeral per-process value. All sessions will be invalidated on "
                    "restart, and process-local peppers are unsuitable for a "
                    "multi-instance deployment (every instance must share the same "
                    "configured value). This is refused outright in production."
                ),
            },
        )

    app.state.redis_client = None
    if settings.REDIS_ENABLED:
        client = create_redis_client(settings)
        healthy = await check_redis_health(client, settings.REDIS_CONNECT_TIMEOUT_SECONDS)
        logger.info(
            "redis_startup_healthcheck",
            extra={"healthy": healthy, "redis_url": mask_redis_url(settings.REDIS_URL)},
        )
        app.state.redis_client = client

    # Local-development convenience only (see ANALYSIS_EMBEDDED_WORKER_ENABLED
    # and app/workers/embedded.py): runs the exact same
    # app.workers.analysis_worker.run_worker() loop the standalone
    # `python -m app.workers.analysis_worker` process uses, on a background
    # thread of this process. start_embedded_worker() itself no-ops when the
    # setting is false or a worker is already running in this process, and
    # is only ever invoked from here (lifespan startup) -- never at import
    # time, so it never runs in uvicorn --reload's file-watching supervisor
    # process, which does not execute the ASGI lifespan protocol.
    app.state.embedded_worker_handle = start_embedded_worker(settings)

    yield

    stop_embedded_worker(app.state.embedded_worker_handle)

    if app.state.redis_client is not None:
        await app.state.redis_client.aclose()
    engine.dispose()
    logger.info("application_shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware, settings=settings)

if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health_router)
app.include_router(api_router)
