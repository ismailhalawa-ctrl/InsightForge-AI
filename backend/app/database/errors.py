import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import OperationalError

from app.exceptions.availability import DatabaseUnavailableError

logger = logging.getLogger(__name__)


@contextmanager
def translate_operational_errors(operation: str, video_id: str | None = None) -> Iterator[None]:
    try:
        yield
    except OperationalError as exc:
        logger.error(
            "database_unavailable",
            extra={
                "operation": operation,
                "video_id": video_id,
                "failure_category": "database",
                "exception_type": type(exc.orig).__name__ if exc.orig else type(exc).__name__,
            },
        )
        raise DatabaseUnavailableError() from exc
