from enum import StrEnum


class SourceType(StrEnum):
    youtube = "youtube"
    github = "github"
    file_import = "file_import"
    app_store = "app_store"
    google_play = "google_play"
    support = "support"
    survey = "survey"
    custom = "custom"
    paste_text = "paste_text"
    web_page = "web_page"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    retrying = "retrying"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.completed, JobStatus.failed, JobStatus.cancelled})
CLAIMABLE_JOB_STATUSES = frozenset({JobStatus.queued, JobStatus.retrying})


class JobStage(StrEnum):
    validating_source = "validating_source"
    loading_metadata = "loading_metadata"
    collecting_comments = "collecting_comments"
    processing_text = "processing_text"
    running_text_intelligence = "running_text_intelligence"
    running_sentiment = "running_sentiment"
    aggregating = "aggregating"
    storing_result = "storing_result"
    completed = "completed"


class CollectionMode(StrEnum):
    bounded = "bounded"
    all_available = "all_available"


class SentimentMode(StrEnum):
    """Sprint 33: how much LLM escalation runs on top of the FAST
    (Sprint <=32) pipeline. FAST is the production default -- identical
    behavior to before this sprint, no LLM calls."""

    fast = "fast"
    hybrid = "hybrid"
    smart = "smart"


class CommentOrder(StrEnum):
    """Maps directly to YouTube Data API v3's commentThreads.list `order`
    parameter values. Deliberately does not have a third "default" member --
    the absence of a value (comment_order=None) is what preserves the
    pre-Sprint-29 behavior of never sending `order` at all, and that
    "unset" state is expressed as `CommentOrder | None`, not as a member of
    this enum.
    """

    relevance = "relevance"
    time = "time"


class InsightCapability(StrEnum):
    overview = "overview"
    topics = "topics"
    complaints = "complaints"
    suggestions = "suggestions"
    questions = "questions"
    praise = "praise"
    criticism = "criticism"
    audience_requests = "audience_requests"
    audience_personas = "audience_personas"
    repeated_themes = "repeated_themes"
    recommendations = "recommendations"
    complete_report = "complete_report"
    # GitHub repository intelligence (Phase 5). Deliberately NOT part of the
    # complete_report lineage: that lineage is feedback-semantic and reads
    # only clean-analysis evidence, whereas this capability is generated from
    # REFERENCE content (repository documents) plus, when present, community
    # records. Storing it in the same analysis_job_insights table reuses the
    # existing cache key/versioning/persistence discipline without giving
    # repository documents any route into feedback semantics.
    # `capability` is a plain varchar(32) with no CHECK constraint, so adding
    # a member needs no migration.
    repository_intelligence = "repository_intelligence"


class InsightMode(StrEnum):
    local = "local"
    ai = "ai"
    hybrid = "hybrid"


class InsightProvider(StrEnum):
    lmstudio = "lmstudio"
    gemini = "gemini"
    openai = "openai"
    none = "none"


class OutputLanguage(StrEnum):
    auto = "auto"
    ar = "ar"
    en = "en"


class InsightStatus(StrEnum):
    # Claimed and in flight. Written BEFORE generation starts so that "no row
    # at all" can mean exactly one thing -- this analysis never reached
    # generation -- instead of being ambiguous between "still running" and
    # "predates the capability". See RepositoryIntelligenceGenerator.
    #
    # Stored as a plain string (native_enum=False, no CHECK constraint), so
    # adding this member needs no migration and older rows are unaffected.
    pending = "pending"
    completed = "completed"
    failed = "failed"


class FallbackReason(StrEnum):
    missing_key = "missing_key"
    missing_model = "missing_model"
    timeout = "timeout"
    rate_limit = "rate_limit"
    provider_unavailable = "provider_unavailable"
    invalid_json = "invalid_json"
    schema_validation_failed = "schema_validation_failed"
    invalid_evidence_reference = "invalid_evidence_reference"
    empty_response = "empty_response"


class UserRole(StrEnum):
    user = "user"
    admin = "admin"


class UserStatus(StrEnum):
    active = "active"
    disabled = "disabled"


class AuditEventType(StrEnum):
    login_succeeded = "login_succeeded"
    login_failed = "login_failed"
    account_locked = "account_locked"
    logout = "logout"
    logout_all = "logout_all"
    refresh_token_reused = "refresh_token_reused"
    user_registered = "user_registered"
    role_changed = "role_changed"
    status_changed = "status_changed"
    admin_cross_user_access = "admin_cross_user_access"
    email_verification_requested = "email_verification_requested"
    email_verified = "email_verified"
    password_reset_requested = "password_reset_requested"
    password_reset_completed = "password_reset_completed"
    security_token_reuse = "security_token_reuse"
    session_listed = "session_listed"
    session_revoked = "session_revoked"
    email_delivery_succeeded = "email_delivery_succeeded"
    email_delivery_failed = "email_delivery_failed"
    rate_limit_backend_unavailable = "rate_limit_backend_unavailable"
    display_name_changed = "display_name_changed"
    account_deleted = "account_deleted"
    plan_changed = "plan_changed"


class AuditEventResult(StrEnum):
    success = "success"
    failure = "failure"


class SecurityTokenPurpose(StrEnum):
    email_verification = "email_verification"
    password_reset = "password_reset"


class EmailOutboxStatus(StrEnum):
    pending = "pending"
    sending = "sending"
    sent = "sent"
    failed = "failed"


class EmailTemplate(StrEnum):
    email_verification = "email_verification"
    password_reset = "password_reset"
    password_changed = "password_changed"
    new_login = "new_login"
    refresh_token_replay = "refresh_token_replay"
    contact_message_received = "contact_message_received"


class ContactInquiryType(StrEnum):
    """Values match the frontend's landing-page Contact form exactly
    (frontend/src/lib/validation.ts::inquiryTypes) -- human-readable
    labels, not snake_case, so no mapping layer is needed between the two."""

    product_feedback = "Product Feedback"
    collaboration = "Collaboration"
    technical_inquiry = "Technical Inquiry"
    business_inquiry = "Business Inquiry"
    bug_report = "Bug Report"


class UserPlan(StrEnum):
    free = "free"
    pro = "pro"


class DatasetType(StrEnum):
    video_comments = "video_comments"
    repository_feedback = "repository_feedback"
    app_reviews = "app_reviews"
    support_tickets = "support_tickets"
    survey_responses = "survey_responses"
    custom_feedback = "custom_feedback"
    web_page = "web_page"


class RecordType(StrEnum):
    comment = "comment"
    reply = "reply"
    review = "review"
    issue = "issue"
    issue_comment = "issue_comment"
    pull_request = "pull_request"
    review_comment = "review_comment"
    release = "release"
    discussion = "discussion"
    ticket = "ticket"
    survey_response = "survey_response"
    custom = "custom"
    # Human-readable project documentation (README, docs/, CONTRIBUTING...).
    # Reference material, NOT audience feedback -- see REFERENCE_RECORD_TYPES.
    repository_document = "repository_document"


# Record types that are REFERENCE material rather than someone's opinion.
#
# The distinction is not cosmetic. Every sentiment percentage, complaint,
# praise cluster and topic in this product answers "what are people saying",
# and a repository's own README is not a person saying anything -- averaging
# it into that would silently move the numbers it is supposed to describe. So
# reference records are collected, analyzed and made retrievable for
# grounding, but are kept out of feedback aggregation entirely (see
# AnalysisJobRunner._build_evidence_row and _run_analysis_in_batches).
#
# Deliberately a source-agnostic set keyed on record type: any future source
# with documentation-shaped content joins by adding its type here, with no
# new branch anywhere else.
REFERENCE_RECORD_TYPES = frozenset({RecordType.repository_document})


class SourceConnectionStatus(StrEnum):
    active = "active"
    disabled = "disabled"
    error = "error"


class SourceDatasetStatus(StrEnum):
    active = "active"
    archived = "archived"


class CollectionState(StrEnum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class FileImportFormat(StrEnum):
    csv = "csv"
    xlsx = "xlsx"
    json = "json"


class FileImportAnalysisMode(StrEnum):
    """Which pipeline an uploaded file feeds.

    `records` is the pre-Sprint-27 behaviour and remains the default for
    every existing row: one chosen text column becomes SourceRecords and the
    generic feedback pipeline (sentiment, insights, signals) runs over them.

    `dataset` runs Universal Dataset Intelligence (app/datasets) over the
    whole table -- schema detection, profiling, quality, relationships,
    trends, per-column text analysis and evidence-grounded insights -- with
    no column mapping required from the user.

    Stored as a plain varchar with no CHECK constraint, so adding a member
    needs no migration.
    """

    records = "records"
    dataset = "dataset"


class FileImportStatus(StrEnum):
    uploaded = "uploaded"
    profiling = "profiling"
    awaiting_mapping = "awaiting_mapping"
    ready = "ready"
    importing = "importing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    expired = "expired"


TERMINAL_FILE_IMPORT_STATUSES = frozenset(
    {
        FileImportStatus.completed,
        FileImportStatus.failed,
        FileImportStatus.cancelled,
        FileImportStatus.expired,
    }
)


class SignalType(StrEnum):
    problem = "problem"
    feature_request = "feature_request"
    question = "question"
    praise = "praise"
    opportunity = "opportunity"
    risk = "risk"


# Signal types an explainable 0-100 priority score is computed for (Sprint 17
# Part 6). Praise and ordinary questions are deliberately excluded -- a
# score would misleadingly imply urgency for a strength or a routine
# information need, neither of which needs triage the way a problem,
# feature_request, or risk does.
PRIORITIZED_SIGNAL_TYPES = frozenset(
    {SignalType.problem, SignalType.feature_request, SignalType.risk}
)


class SignalSeverity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class SignalEvidenceRole(StrEnum):
    primary = "primary"
    supporting = "supporting"
    contradicting = "contradicting"


class RecommendationUrgency(StrEnum):
    now = "now"
    next = "next"
    later = "later"


class ConnectorCredentialType(StrEnum):
    personal_access_token = "personal_access_token"


class GitHubRepositoryState(StrEnum):
    open = "open"
    closed = "closed"
    all = "all"


class RecommendationActionStatus(StrEnum):
    """Status of one analysis recommendation (Product Intelligence
    Expansion). Three states on purpose -- this is a checklist, not a
    project tracker; ActionPlanStatus is the richer lifecycle."""

    open = "open"
    in_progress = "in_progress"
    addressed = "addressed"


class ActionPlanStatus(StrEnum):
    draft = "draft"
    open = "open"
    in_progress = "in_progress"
    blocked = "blocked"
    monitoring = "monitoring"
    completed = "completed"
    cancelled = "cancelled"


class ActionPlanPriority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ActionTaskStatus(StrEnum):
    todo = "todo"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"
    cancelled = "cancelled"


class ActionPlanEventType(StrEnum):
    plan_created = "plan_created"
    plan_created_from_signal = "plan_created_from_signal"
    plan_status_changed = "plan_status_changed"
    plan_priority_changed = "plan_priority_changed"
    plan_due_date_changed = "plan_due_date_changed"
    plan_archived = "plan_archived"
    plan_restored = "plan_restored"
    plan_completed = "plan_completed"
    plan_reopened = "plan_reopened"
    task_created = "task_created"
    task_updated = "task_updated"
    task_reordered = "task_reordered"
    task_deleted = "task_deleted"


TERMINAL_ACTION_PLAN_STATUSES = frozenset({ActionPlanStatus.completed, ActionPlanStatus.cancelled})
TERMINAL_ACTION_TASK_STATUSES = frozenset({ActionTaskStatus.done, ActionTaskStatus.cancelled})


class ComparisonType(StrEnum):
    job_to_job = "job_to_job"
    before_after_event = "before_after_event"
    action_outcome = "action_outcome"


class ComparisonStatus(StrEnum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class SignalTrendDirection(StrEnum):
    new = "new"
    rising = "rising"
    stable = "stable"
    falling = "falling"
    resolved = "resolved"
    insufficient_data = "insufficient_data"


class ActionOutcomeResult(StrEnum):
    improved = "improved"
    unchanged = "unchanged"
    worsened = "worsened"
    resolved = "resolved"
    inconclusive = "inconclusive"


class SuggestedNextStatus(StrEnum):
    continue_monitoring = "continue_monitoring"
    consider_completion = "consider_completion"
    reopen_investigation = "reopen_investigation"
    insufficient_evidence = "insufficient_evidence"


class QueryIntent(StrEnum):
    top_signals = "top_signals"
    trend_summary = "trend_summary"
    priority_explanation = "priority_explanation"
    evidence_lookup = "evidence_lookup"
    outcome_summary = "outcome_summary"
    sentiment_summary = "sentiment_summary"
    distribution_summary = "distribution_summary"
    action_plan_progress = "action_plan_progress"
    unsupported = "unsupported"


class QueryAnswerType(StrEnum):
    list = "list"
    comparison = "comparison"
    explanation = "explanation"
    summary = "summary"
    count = "count"
    progress = "progress"
    unsupported = "unsupported"


class QueryMode(StrEnum):
    local = "local"
    provider = "provider"
    auto = "auto"


class ReportType(StrEnum):
    executive_brief = "executive_brief"
    product_feedback = "product_feedback"
    release_impact = "release_impact"
    github_repository_health = "github_repository_health"
    action_outcome = "action_outcome"


class ReportStatus(StrEnum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class ReportScopeType(StrEnum):
    job = "job"
    dataset = "dataset"
    comparison = "comparison"
    action_plan = "action_plan"


class ReportExportFormat(StrEnum):
    pdf = "pdf"
    docx = "docx"
    json = "json"
    csv = "csv"
    xlsx = "xlsx"


class ReportExportStatus(StrEnum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class InputType(StrEnum):
    """What app/services/sources/detector.py classified a raw user-supplied
    reference as. Distinct from SourceType: an InputType is a shape the
    reference matched (e.g. "this looks like a GitHub pull request URL"),
    while SourceType is which connector would ultimately handle it -- several
    InputTypes (youtube_video/channel/playlist) map to one SourceType.
    """

    youtube_video = "youtube_video"
    youtube_channel = "youtube_channel"
    youtube_playlist = "youtube_playlist"
    github_repository = "github_repository"
    github_issue = "github_issue"
    github_pull_request = "github_pull_request"
    google_play_app = "google_play_app"
    app_store_app = "app_store_app"
    generic_url = "generic_url"
    pasted_text = "pasted_text"
    file_reference = "file_reference"
    unknown = "unknown"


class DetectionStatus(StrEnum):
    """Whether a detected InputType can actually be collected right now."""

    supported = "supported"
    supported_later = "supported_later"
    ambiguous = "ambiguous"
    unsupported = "unsupported"


class AssistantScopeType(StrEnum):
    """Scope of an AssistantSession's retrieval -- resolved once at session
    creation and re-validated (never trusted from a stored value alone) on
    every message send. "all" searches every completed analysis the user
    owns; "source" restricts to one SourceType; "job" restricts to exactly
    one completed analysis, whose ownership is re-checked per message."""

    all = "all"
    source = "source"
    job = "job"


class AssistantMessageRole(StrEnum):
    user = "user"
    assistant = "assistant"


class PasteTextSplitMode(StrEnum):
    single_block = "single_block"
    lines = "lines"


class PasteTextAnalysisMode(StrEnum):
    """What the pasted text IS, which decides how it is analysed.

    `document` -- one artifact: a report, transcript, article or set of
    notes. Measured and interpreted as a document by Pasted Text
    Intelligence; no SourceRecords are created and nothing is scored as
    audience feedback.

    `records` -- many people's utterances, one per line: a pasted list of
    reviews or survey answers. Takes the unchanged record pipeline, which is
    what this source did before the document mode existed.
    """

    document = "document"
    records = "records"
