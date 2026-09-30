from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import (
    DatasetType,
    FileImportAnalysisMode,
    FileImportFormat,
    FileImportStatus,
    JobStatus,
)


class ColumnProfileResponse(BaseModel):
    name: str
    inferred_type: str
    null_percentage: float
    unique_count: int
    sample_values: list[str]


class ParseWarningResponse(BaseModel):
    code: str
    message: str
    row_number: int | None = None


class FileProfileResponse(BaseModel):
    detected_format: FileImportFormat
    columns: list[ColumnProfileResponse]
    sample_row_count: int
    profile_complete: bool
    estimated_row_count: int | None
    warnings: list[ParseWarningResponse]
    sheets: list[str] | None = None
    json_paths: list[str] | None = None
    delimiter: str | None = None
    encoding: str | None = None
    suggested_mapping: dict[str, str]


class FileImportUploadResponse(BaseModel):
    import_id: UUID
    status: FileImportStatus
    detected_format: FileImportFormat
    original_filename: str
    file_size_bytes: int
    profile: FileProfileResponse
    expires_at: datetime
    # Whether Universal Dataset Intelligence can analyze this file as a
    # table. False for JSON, which the import layer parses for the record
    # pipeline but which is not necessarily rectangular -- the wizard reads
    # this rather than hard-coding a format list that could drift.
    dataset_analysis_supported: bool = False


class ColumnMappingRequest(BaseModel):
    text_column: str = Field(min_length=1, max_length=255)
    external_id_column: str | None = None
    occurred_at_column: str | None = None
    author_reference_column: str | None = None
    parent_external_id_column: str | None = None
    thread_reference_column: str | None = None
    rating_column: str | None = None
    language_column: str | None = None
    record_type_column: str | None = None
    engagement_columns: dict[str, str] = {}
    metadata_columns: list[str] = []
    default_record_type: str = "custom"
    default_source_label: str | None = None
    occurred_at_format: str | None = None
    rating_min: float | None = None
    rating_max: float | None = None
    empty_text_policy: Literal["skip", "allow"] = "skip"


class ParserOptionsRequest(BaseModel):
    sheet_name: str | None = None
    json_path: str | None = None
    delimiter: str | None = None
    encoding: str | None = None
    header_row: int = Field(default=1, ge=1, le=1000)


class FileImportConfigureRequest(BaseModel):
    dataset_title: str = Field(min_length=1, max_length=255)
    dataset_type: DatasetType
    # Optional, because dataset intelligence needs no column mapping at all:
    # the whole table is analyzed and every column's meaning is detected. The
    # record pipeline still requires one, and the service rejects a
    # mapping-less `records` configuration rather than defaulting a column.
    mapping: ColumnMappingRequest | None = None
    parser_options: ParserOptionsRequest = ParserOptionsRequest()
    analysis_mode: FileImportAnalysisMode = FileImportAnalysisMode.dataset


class FileImportSummaryResponse(BaseModel):
    id: UUID
    status: FileImportStatus
    detected_format: FileImportFormat
    original_filename: str
    dataset_title: str | None
    dataset_type: str | None
    file_size_bytes: int
    row_count: int | None
    valid_row_count: int
    invalid_row_count: int
    duplicate_row_count: int
    analysis_mode: str
    source_dataset_id: UUID | None
    analysis_job_id: UUID | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class FileImportDetailResponse(FileImportSummaryResponse):
    profile: FileProfileResponse
    mapping: ColumnMappingRequest | None


class FileImportListResponse(BaseModel):
    imports: list[FileImportSummaryResponse]
    total: int
    limit: int
    offset: int


class FileImportStartRequest(BaseModel):
    comment_limit: int | None = None
    # Dataset-intelligence imports only: analyze every retained text row
    # instead of the bounded per-column sample. Changes analysis coverage,
    # never the uploaded file.
    full_text_analysis: bool = False


class FileImportStartResponse(BaseModel):
    import_id: UUID
    status: FileImportStatus
    job_id: UUID
    job_status: JobStatus


class PreviewRequest(BaseModel):
    mapping: ColumnMappingRequest


class PreviewRowResponse(BaseModel):
    text: str | None
    external_id: str | None
    record_type: str
    occurred_at: str | None
    rating: float | None
    language: str | None
    author_reference: str | None


class PreviewResponse(BaseModel):
    rows: list[PreviewRowResponse]


class InvalidRowResponse(BaseModel):
    row_number: int
    location: str | None
    field: str | None
    error_code: str
    message: str
    created_at: datetime


class InvalidRowListResponse(BaseModel):
    rows: list[InvalidRowResponse]
    persisted_total: int
    total_invalid_rows: int
    limit: int
    offset: int


class FileImportCancelResponse(BaseModel):
    import_id: UUID
    status: FileImportStatus
