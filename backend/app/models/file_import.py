import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import FileImportAnalysisMode, FileImportFormat, FileImportStatus

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")

FILE_IMPORT_ERROR_MESSAGE_MAX_CHARS = 500


class FileImport(Base):
    """One user-uploaded CSV/XLSX/JSON file moving through the two-phase
    upload -> profile -> configure -> start workflow (see app/imports/service.py).

    Never stores a client filesystem path or raw file bytes -- `storage_key`
    is an opaque, server-generated identifier resolved through the
    ImportFileStorage abstraction (app/imports/storage.py), never a path a
    caller supplied. Ownership always comes from the authenticated principal
    that created the row, exactly like SourceDataset/AnalysisJob.
    """

    __tablename__ = "file_imports"
    __table_args__ = (
        Index("ix_file_import_user_id", "user_id"),
        Index("ix_file_import_status", "status"),
        Index("ix_file_import_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_datasets.id", ondelete="SET NULL"), nullable=True
    )
    analysis_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="SET NULL"), nullable=True
    )

    original_filename: Mapped[str] = mapped_column(String(255))
    detected_format: Mapped[FileImportFormat] = mapped_column(
        Enum(FileImportFormat, native_enum=False, length=16, validate_strings=True)
    )
    status: Mapped[FileImportStatus] = mapped_column(
        Enum(FileImportStatus, native_enum=False, length=32, validate_strings=True),
        default=FileImportStatus.uploaded,
    )

    storage_key: Mapped[str] = mapped_column(String(64))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    file_sha256: Mapped[str] = mapped_column(String(64))
    file_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_row_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_row_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_row_count: Mapped[int] = mapped_column(Integer, default=0)

    profile: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    mapping: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)
    parser_options: Mapped[dict] = mapped_column(_JSONVariant, default=dict)

    # Which pipeline this upload feeds -- see FileImportAnalysisMode. Plain
    # string with a server default of "records" so every pre-existing row
    # reads as the behaviour it actually had, with no backfill.
    analysis_mode: Mapped[str] = mapped_column(
        String(16),
        default=FileImportAnalysisMode.records.value,
        server_default=FileImportAnalysisMode.records.value,
    )

    dataset_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dataset_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_record_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(
        String(FILE_IMPORT_ERROR_MESSAGE_MAX_CHARS), nullable=True
    )

    version: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FileImportRowError(Base):
    """One rejected row from a file import, capped at
    settings.FILE_IMPORT_MAX_PERSISTED_ROW_ERRORS per import -- see
    FileImportRowErrorRepository. FileImport.invalid_row_count is the
    authoritative total and keeps counting past that cap; this table only
    ever holds a bounded sample for user-facing diagnostics, never every
    invalid row in a pathological file, and never the row's raw content.
    """

    __tablename__ = "file_import_row_errors"
    __table_args__ = (Index("ix_file_import_row_error_import_id", "file_import_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_import_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("file_imports.id", ondelete="CASCADE")
    )

    row_number: Mapped[int] = mapped_column(Integer)
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(FILE_IMPORT_ERROR_MESSAGE_MAX_CHARS))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
