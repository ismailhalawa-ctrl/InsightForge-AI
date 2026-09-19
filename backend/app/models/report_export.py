import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import ReportExportFormat, ReportExportStatus

REPORT_EXPORT_FILENAME_MAX_CHARS = 255
REPORT_EXPORT_CONTENT_TYPE_MAX_CHARS = 128
REPORT_EXPORT_ERROR_MESSAGE_MAX_CHARS = 500
REPORT_EXPORT_STORAGE_PATH_MAX_CHARS = 64


class ReportExport(Base):
    """One rendered export of an existing Report (Sprint 22). Never stores
    file bytes here -- `storage_path` is an opaque, server-generated key
    resolved through app/services/exports/storage.py's storage abstraction,
    the same never-a-real-path-or-client-value pattern FileImport.storage_key
    uses. Rendering only ever reads the report's already-persisted `content`
    (see app/services/exports/normalize.py); it never recomputes a metric or
    calls an LLM.
    """

    __tablename__ = "report_exports"
    __table_args__ = (
        Index("ix_report_export_user_id", "user_id"),
        Index("ix_report_export_report_id", "report_id"),
        Index("ix_report_export_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )

    format: Mapped[ReportExportFormat] = mapped_column(
        Enum(ReportExportFormat, native_enum=False, length=8, validate_strings=True)
    )
    status: Mapped[ReportExportStatus] = mapped_column(
        Enum(ReportExportStatus, native_enum=False, length=16, validate_strings=True),
        default=ReportExportStatus.pending,
    )

    storage_path: Mapped[str | None] = mapped_column(
        String(REPORT_EXPORT_STORAGE_PATH_MAX_CHARS), nullable=True
    )
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[str] = mapped_column(String(REPORT_EXPORT_CONTENT_TYPE_MAX_CHARS))
    original_filename: Mapped[str] = mapped_column(String(REPORT_EXPORT_FILENAME_MAX_CHARS))
    file_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_message: Mapped[str | None] = mapped_column(
        String(REPORT_EXPORT_ERROR_MESSAGE_MAX_CHARS), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
