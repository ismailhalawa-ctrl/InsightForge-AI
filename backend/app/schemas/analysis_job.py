from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import (
    CollectionMode,
    CommentOrder,
    JobStage,
    JobStatus,
    SentimentMode,
    SourceType,
)
from app.schemas.video_sentiment import SentimentExample, VideoSentimentSummary

REPORT_SCHEMA_VERSION = 1


class AnalysisJobCreateRequest(BaseModel):
    source_type: SourceType = SourceType.youtube
    source: str = Field(min_length=1, max_length=2048)
    comment_limit: int | None = None
    collection_mode: CollectionMode = CollectionMode.bounded
    # YouTube-only (Sprint 29); silently unused by every other source_type,
    # matching how comment_limit itself already only applies to comment
    # collection. comment_order=None preserves the pre-Sprint-29 behavior of
    # never sending an `order` param to the YouTube API at all.
    comment_order: CommentOrder | None = None
    include_replies: bool = False
    # Sprint 32: optional override of SENTIMENT_MIN_CONFIDENCE for this job
    # only. None uses the production default. Validated against a safe
    # operational range (see AnalysisJobService._resolve_confidence_threshold),
    # not the full 0.0-1.0 domain.
    confidence_threshold: float | None = None
    # Sprint 33: FAST (default, identical to pre-Sprint-33 behavior) /
    # HYBRID (escalate only "hard" comments to an LLM) / SMART (escalate
    # every eligible, deduplicated comment). FAST never calls an LLM.
    sentiment_mode: SentimentMode = SentimentMode.fast


class AnalysisJobFromDatasetRequest(BaseModel):
    source_dataset_id: UUID
    comment_limit: int | None = None
    # Only meaningful when re-analyzing a YouTube dataset; harmless no-ops
    # for every other source_type. skip_collection=True means a job created
    # here never actually re-collects, so these have no effect on the
    # resulting job's behavior -- they exist so "Run Again" can honestly
    # preserve and display what the original collection actually used
    # (see AnalysisJobService.create_job_from_dataset's docstring).
    collection_mode: CollectionMode = CollectionMode.bounded
    comment_order: CommentOrder | None = None
    include_replies: bool = False
    # Same override as AnalysisJobCreateRequest.confidence_threshold -- not
    # auto-copied from the original job, exactly like collection_mode; the
    # caller passes it explicitly so "Run Again" can honestly preserve it.
    confidence_threshold: float | None = None
    # Same convention as confidence_threshold -- "Run Again" passes the
    # original job's sentiment_mode explicitly (see the frontend wiring),
    # it is not auto-copied server-side.
    sentiment_mode: SentimentMode = SentimentMode.fast
    # Dataset re-analysis only: lift the per-column text sampling cap so the
    # NLP stage reads every text row. Ignored by every connector-backed
    # source, none of which samples text in the first place.
    full_text_analysis: bool = False


class AnalysisJobCreatedResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    stage: JobStage
    source_type: SourceType
    source_dataset_id: UUID | None = None
    requested_comment_limit: int
    collection_mode: CollectionMode
    comment_order: CommentOrder | None = None
    include_replies: bool = False
    confidence_threshold: float | None = None
    sentiment_mode: SentimentMode
    created_at: datetime


class AnalysisJobProgress(BaseModel):
    progress_percentage: float
    stage_progress_percentage: float
    current_stage: JobStage
    status_message: str | None
    comments_discovered: int
    comments_collected: int
    comments_available: int
    comments_processed: int
    comments_analyzed: int
    comments_failed: int
    collection_complete: bool
    # Sprint 34: "source_exhausted" (the source itself had no more data)
    # vs "account_cap_reached" (requested_comment_limit was hit first) vs
    # None (still collecting). See AnalysisJob.collection_stop_reason.
    collection_stop_reason: str | None = None


class AnalysisJobStatusResponse(BaseModel):
    job_id: UUID
    source_type: SourceType
    source_reference: str
    source_external_id: str | None
    source_dataset_id: UUID | None
    # Whether this job produces Universal Dataset Intelligence rather than
    # the record/feedback report. Carried on the STATUS response because the
    # frontend dispatches its whole result experience on it -- the same way
    # it dispatches on source_type for GitHub -- and must be able
    # to do so from the status it is already polling, without a speculative
    # request to an endpoint that may 404.
    #
    # Resolved from the dataset, not the source type: a future Google Sheets
    # or Forms connector produces dataset analyses too, and this stays
    # correct for it with no change here.
    is_dataset_analysis: bool = False
    is_web_page_analysis: bool = False
    is_text_analysis: bool = False
    status: JobStatus
    progress: AnalysisJobProgress
    requested_comment_limit: int
    collection_mode: CollectionMode
    comment_order: CommentOrder | None = None
    include_replies: bool = False
    confidence_threshold: float | None = None
    sentiment_mode: SentimentMode
    attempt_count: int
    max_attempts: int
    cancellation_requested: bool
    # Derived, server-computed action availability -- the single source of
    # truth for which lifecycle actions are currently valid, so the frontend
    # never has to duplicate the status-transition rules itself (see
    # app/api/v1/analysis_jobs.py's _can_cancel/_can_retry/_can_run_again).
    can_cancel: bool
    can_retry: bool
    can_run_again: bool
    error_code: str | None
    error_message: str | None
    # When a retrying job will next be picked up. Normally a few seconds of
    # backoff, but for a source quota wait (see SourceQuotaExhaustedError) it
    # can be up to an hour out -- which is exactly when the UI needs to say
    # "waiting until HH:MM" rather than leaving a paused job looking stuck.
    next_attempt_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    cancelled_at: datetime | None
    failed_at: datetime | None


class AnalysisJobListItem(BaseModel):
    job_id: UUID
    source_type: SourceType
    source_external_id: str | None
    status: JobStatus
    stage: JobStage
    progress_percentage: float
    created_at: datetime
    completed_at: datetime | None
    # A real, human-readable title -- the source dataset's display_name
    # (backfilled with the real video title / repo full name / filename /
    # pasted-text title shortly after collection starts; see
    # AnalysisJobRunner._prepare_collection's describe_source() call), never
    # a fabricated one. Falls back to "<source_type>: <external_id or
    # 'pending'>" only for the brief window before that backfill lands.
    title: str
    # Only ever populated for YouTube (from the cached YouTubeVideo row) --
    # no other connector has a thumbnail concept yet. None renders as a
    # source-type icon on the frontend instead of a fabricated image.
    thumbnail_url: str | None = None
    # Real records collected for this job so far (job.comments_collected) --
    # source-agnostic, always populated, never a stand-in for comments_analyzed.
    comment_count: int
    # Both null until the job has a persisted report (status == completed).
    # The dominant of positive/negative/neutral (excluding "uncertain", which
    # is a confidence outcome, not a sentiment) -- deliberately not the
    # same as VideoSentimentSummary.overall_sentiment, which uses a
    # different, coarser "balanced/unknown" classification.
    dominant_sentiment: str | None = None
    dominant_sentiment_percentage: float | None = None
    # Universal Dataset Intelligence. True as soon as the job's dataset is
    # marked for it -- History can therefore label a dataset analysis while
    # it is still running and route "View Details" to the dataset result
    # experience. The four numbers below stay null until the analysis is
    # persisted, so History never shows a row count it does not have.
    is_dataset_analysis: bool = False
    is_web_page_analysis: bool = False
    is_text_analysis: bool = False
    web_page_url: str | None = None
    web_page_type: str | None = None
    text_title: str | None = None
    text_word_count: int | None = None
    text_language: str | None = None
    dataset_file_name: str | None = None
    dataset_file_type: str | None = None
    dataset_row_count: int | None = None
    dataset_column_count: int | None = None
    dataset_health_score: int | None = None


class AnalysisJobListResponse(BaseModel):
    jobs: list[AnalysisJobListItem]
    total: int
    limit: int
    offset: int


class AnalysisJobDeleteAllResponse(BaseModel):
    deleted_count: int


class AnalysisReport(BaseModel):
    job_id: UUID
    source_type: SourceType
    source_external_id: str
    schema_version: int = REPORT_SCHEMA_VERSION
    requested_comment_limit: int
    collected_count: int
    collection_complete: bool
    processing_duration_ms: float
    worker_attempts: int
    completed_at: datetime
    # Optional/defaulted so reports persisted before this field existed still
    # deserialize cleanly -- old rows simply come back with sentiment_mode=None.
    sentiment_mode: SentimentMode | None = None
    # Whether the AI review the chosen mode promised actually completed in
    # full. A HYBRID/SMART run whose local model was unavailable still
    # produces a correct report -- every comment keeps its classifier label --
    # but it is not the analysis the user asked for, and presenting it as one
    # would be dishonest. None on FAST (nothing was promised) and on reports
    # persisted before this field existed.
    ai_review_complete: bool | None = None
    # How many comments kept their classifier label because escalation could
    # not reach them (provider failure, or budget/time exhausted).
    ai_review_skipped_count: int | None = None
    summary: VideoSentimentSummary
    positive_examples: list[SentimentExample]
    negative_examples: list[SentimentExample]
    neutral_examples: list[SentimentExample]
    uncertain_examples: list[SentimentExample]


class AnalysisJobResultResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    report: AnalysisReport


class AnalysisJobCancelResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    cancellation_requested: bool
    message: str


class AnalysisJobRetryResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    message: str
