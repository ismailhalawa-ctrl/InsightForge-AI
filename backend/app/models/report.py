import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import InsightProvider, ReportScopeType, ReportStatus, ReportType

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")

REPORT_TITLE_MAX_CHARS = 255
REPORT_ERROR_MESSAGE_MAX_CHARS = 500
REPORT_MODEL_NAME_MAX_CHARS = 128
REPORT_ALGORITHM_VERSION_MAX_CHARS = 16
REPORT_INPUT_FINGERPRINT_MAX_CHARS = 64
REPORT_IDEMPOTENCY_KEY_MAX_CHARS = 255


class Report(Base):
    """A persisted, structured (JSON, never prose-only) report generated
    once from a user's own already-analyzed data (Sprint 21). Reuses the
    exact same deterministic retrieval (app/services/query/retrieval.py)
    that Ask Your Data uses -- a report's `content` is built from the same
    bounded, ownership-scoped context, never a full-dataset dump, and any
    optional AI narrative section can only explain that already-final
    content, never invent a count, cause, user, release, or outcome.

    `scope_id` is a deliberately polymorphic reference (its target table
    depends on `scope_type`: job/dataset/comparison/action_plan), so it is
    NOT a hard foreign key -- a single column cannot reference four
    different tables. Ownership and existence are instead verified by the
    service layer at generation time, the same "resolve through the owning
    repository, 404 if missing or unowned" discipline used everywhere else
    in this codebase, just applied across four possible source tables
    instead of one.

    `input_fingerprint` is a SHA-256 hex digest of everything the report's
    content deterministically depends on (scope id, algorithm version, and
    a coarse per-scope data version such as a job's `updated_at`) -- it lets
    a caller detect that a report may be stale without this table ever
    storing a second full snapshot of the underlying data.

    `idempotency_key` is unique per (user_id, idempotency_key), the same
    user-scoped convention every other Sprint 18-20 write endpoint uses --
    a NULL key never collides with another NULL, so only a genuinely
    repeated (user, key) pair is ever rejected.
    """

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_report_user_idempotency_key"),
        Index("ix_report_user_id", "user_id"),
        Index("ix_report_user_type", "user_id", "report_type"),
        Index("ix_report_scope", "scope_type", "scope_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )

    report_type: Mapped[ReportType] = mapped_column(
        Enum(ReportType, native_enum=False, length=32, validate_strings=True)
    )
    title: Mapped[str] = mapped_column(String(REPORT_TITLE_MAX_CHARS))

    scope_type: Mapped[ReportScopeType] = mapped_column(
        Enum(ReportScopeType, native_enum=False, length=16, validate_strings=True)
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))

    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, native_enum=False, length=16, validate_strings=True),
        default=ReportStatus.pending,
    )
    content: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    limitations: Mapped[list] = mapped_column(_JSONVariant, default=list)
    error_message: Mapped[str | None] = mapped_column(
        String(REPORT_ERROR_MESSAGE_MAX_CHARS), nullable=True
    )

    provider_used: Mapped[InsightProvider | None] = mapped_column(
        Enum(InsightProvider, native_enum=False, length=16, validate_strings=True), nullable=True
    )
    model_name: Mapped[str | None] = mapped_column(
        String(REPORT_MODEL_NAME_MAX_CHARS), nullable=True
    )
    algorithm_version: Mapped[str] = mapped_column(String(REPORT_ALGORITHM_VERSION_MAX_CHARS))
    input_fingerprint: Mapped[str] = mapped_column(String(REPORT_INPUT_FINGERPRINT_MAX_CHARS))

    idempotency_key: Mapped[str | None] = mapped_column(
        String(REPORT_IDEMPOTENCY_KEY_MAX_CHARS), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
