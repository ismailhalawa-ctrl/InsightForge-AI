"""Sentiment-over-time, likes-vs-confidence, and paginated comment
analytics for a single job (Phase 1B) -- new endpoints only, no schema
changes: everything here is derived from AnalysisRecordEvidence rows that
already existed. Kept in their own module (not analysis_job.py, which
already owns a different concern) alongside the workspace-wide aggregate
summary, which is deliberately source-agnostic (YouTube/GitHub/File
Import/Paste Text all produce the same VideoSentimentSummary shape today)
and therefore never named/shaped around "video".
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.github_page_views import GithubPageViews
from app.schemas.repository_intelligence import RepositoryIntelligenceEnvelope
from app.schemas.video_sentiment import LanguageBreakdown, OverallSentiment


class SentimentTimelinePoint(BaseModel):
    bucket: date
    positive: int = 0
    negative: int = 0
    neutral: int = 0
    uncertain: int = 0


class SentimentTimelineResponse(BaseModel):
    job_id: UUID
    points: list[SentimentTimelinePoint]


class EngagementPoint(BaseModel):
    like_count: int
    confidence: float
    sentiment: str


class EngagementScatterResponse(BaseModel):
    job_id: UUID
    points: list[EngagementPoint]
    # True when the job has more points than the response includes and
    # deterministic systematic sampling (not just the first N) was used --
    # lets the frontend caption the chart honestly rather than implying
    # every comment is plotted.
    sampled: bool


class CommentListItem(BaseModel):
    id: UUID
    comment: str
    sentiment: str
    language: str
    confidence: float | None
    like_count: int
    is_spam: bool
    is_sarcasm: bool
    occurred_at: str | None


class CommentListResponse(BaseModel):
    job_id: UUID
    items: list[CommentListItem]
    total: int
    limit: int
    offset: int


class GithubCoverageStatus:
    """Enum-like string constants (kept as plain strings, not a pydantic
    Enum, so a future status can be added without a schema migration).

    - complete: every record of this kind was collected AND fully counted.
    - not_collected: this run's GitHubAnalysisRequest never selected this
      entity type (e.g. include_pull_requests=False) -- a 0 here would be a
      lie; the section must say so instead.
    - partial: collection started but did not finish (budget/limit reached,
      or -- for documents specifically -- the repository tree listing itself
      was truncated by GitHub, so document discovery is known-incomplete).
    - rate_limited: collection stopped early because of a GitHub rate limit,
      distinct from an ordinary budget cutoff so the user knows to retry
      later rather than that they simply asked for too few records.
    - unknown: coverage could not be determined from persisted data (should
      be rare -- used only as a safe fallback, never a normal-path status).
    """

    COMPLETE = "complete"
    NOT_COLLECTED = "not_collected"
    PARTIAL = "partial"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


class GithubSectionCoverage(BaseModel):
    status: str
    reason: str | None = None


class GithubCoverage(BaseModel):
    issues: GithubSectionCoverage
    pull_requests: GithubSectionCoverage
    releases: GithubSectionCoverage
    documents: GithubSectionCoverage
    labels: GithubSectionCoverage
    sentiment: GithubSectionCoverage
    contributors: GithubSectionCoverage


class GithubRepositoryHeader(BaseModel):
    full_name: str | None
    description: str | None
    language: str | None
    default_branch: str | None
    stars: int
    forks: int
    subscribers_count: int | None
    open_issues_count: int
    license: str | None
    archived: bool
    pushed_at: str | None
    url: str | None


class GithubSummaryMetrics(BaseModel):
    open_issues: int
    closed_issues: int
    total_pull_requests: int
    open_pull_requests: int
    closed_pull_requests: int
    merged_pull_requests: int
    # merged / total_closed, where total_closed = merged + closed_without_merge.
    # None (not 0.0) when total_closed == 0 -- there is no rate to report,
    # and 0.0 would misleadingly read as "nothing merged" rather than
    # "nothing closed yet".
    merge_rate: float | None
    release_count: int
    documents_analyzed: int


class GithubTimeSeriesPoint(BaseModel):
    bucket: str
    opened: int = 0
    closed: int = 0
    merged: int = 0
    closed_without_merge: int = 0


class GithubIssueStateSlice(BaseModel):
    state: str
    count: int


class GithubLabelCount(BaseModel):
    label: str
    count: int


class GithubReleasePoint(BaseModel):
    bucket: str
    name: str | None
    published_at: str | None
    url: str | None


class GithubEntityComposition(BaseModel):
    issues: int
    pull_requests: int
    releases: int
    documents: int
    other: int = 0


class GithubContributor(BaseModel):
    author: str
    activity_count: int


class GithubFeedbackSentiment(BaseModel):
    positive: int = 0
    negative: int = 0
    neutral: int = 0
    uncertain: int = 0


class GithubDocumentItem(BaseModel):
    """One analyzed repository document, as a named card rather than a raw
    URL. `title` is the filename (never invented); `category` is the
    deterministic document_category() label re-derived from the persisted
    path, so an older record stored before a category existed still labels
    correctly without recollecting anything."""

    path: str
    title: str
    category: str
    truncated: bool
    size_bytes: int | None
    url: str | None


class GithubDocumentCategories(BaseModel):
    """Presence of each documentation category the classifier can decide
    confidently. Every field is derived from document_category() over the
    persisted path -- never from a filename guess in the frontend."""

    readme: bool = False
    architecture: bool = False
    api: bool = False
    deployment: bool = False
    changelog: bool = False
    contributing: bool = False
    security: bool = False
    roadmap: bool = False


class GithubDocumentationGap(BaseModel):
    """A documentation category the classifier did NOT find. Deliberately
    modelled as an absence, not a defect -- optional community-health files
    are not failures, so the frontend wording is "not found in analyzed
    repository documentation", never "missing"."""

    category: str


class GithubDocumentationSummary(BaseModel):
    documents_analyzed: int
    readme_available: bool
    documentation_count: int
    truncated_count: int
    important_document_links: list[str]
    categories: GithubDocumentCategories = GithubDocumentCategories()
    documents: list[GithubDocumentItem] = []
    gaps: list[GithubDocumentationGap] = []


class GithubActivityPresence(BaseModel):
    """Whether each activity analytic has anything real to draw. Lets the
    frontend collapse empty charts into one truthful line instead of
    rendering a grid of "No data available" panels -- WITHOUT conflating
    "zero activity" with "not collected"/"partial", which stay in
    GithubCoverage and are reported separately."""

    has_issues: bool = False
    has_pull_requests: bool = False
    has_releases: bool = False
    has_labels: bool = False
    has_contributors: bool = False
    has_feedback: bool = False

    @property
    def any_activity(self) -> bool:
        return any(
            (
                self.has_issues,
                self.has_pull_requests,
                self.has_releases,
                self.has_labels,
                self.has_contributors,
            )
        )


class GithubActivityNarrative(BaseModel):
    """Plain-language activity facts, computed deterministically.

    Not AI. Every field here is derived from the counts and coverage the
    analytics response already carries, which is why the Activity page reads
    correctly with the provider offline and never waits on a synthesis.

    The distinction this model exists to make explicit:

        COLLECTION COMPLETENESS  did the configured collection phases finish?
        ACTIVITY VOLUME          how much activity was there to collect?

    The old page printed "Activity data coverage: complete" and left the
    reader to guess which one it meant -- and a repository with zero issues
    and a completed collection looks identical to a collection that failed.
    """

    #: One honest sentence about what activity was found, or was not.
    summary: str | None = None
    #: What the collection status actually claims, in words. Never implies
    #: that every kind of GitHub activity was analysed -- InsightForge does
    #: not collect commits or discussions, and saying "complete" without
    #: this note reads as though it did.
    collection_note: str | None = None
    #: Why merge rate is unavailable, when it is. "N/A" with no reason reads
    #: as a defect rather than as an arithmetic impossibility.
    merge_rate_note: str | None = None


class GithubMaturitySignal(BaseModel):
    """A factual, deterministic indicator -- never a synthesised 0-100
    "health score". Each entry is a single yes/no fact the persisted data
    can prove, and the frontend renders it as such."""

    key: str
    present: bool


class GithubRepositoryGlance(BaseModel):
    """ "Repository at a glance", assembled from already-persisted content
    only: a bounded README excerpt (see
    SourceRecordRepository.get_repository_document_excerpts -- the excerpt
    is bounded in SQL, full bodies are never loaded), the documentation
    categories present, and technology names that literally appear in the
    analyzed documentation. No LLM call is made here or anywhere else on
    this endpoint; nothing is generated on page view."""

    summary_excerpt: str | None = None
    summary_source_path: str | None = None
    technologies: list[str] = []
    documented_areas: list[str] = []


class GithubCapabilityAvailability(BaseModel):
    """Which detailed capabilities are worth showing for THIS GitHub analysis.

    Derived server-side from persisted analysis state so the visibility rules
    live in one place rather than being re-implemented across React routes.

    Every flag answers "is there real content behind this page?", never "is
    the page implemented?" -- a capability whose data simply does not exist
    for this repository is hidden rather than rendered empty, which is what
    removes the dead "Not generated yet" navigation.

    `intelligence_status` is deliberately separate from
    `has_repository_intelligence`: "generation failed" and "this job predates
    the capability" are different facts from "there is nothing to show", and
    the UI must be able to tell the user which one applies.
    """

    # Reference/documentation class -- present for any repository with docs.
    has_documents: bool = False
    has_repository_intelligence: bool = False
    # Community class -- everything below requires real community records, so
    # a documentation-only repository correctly reports all of them False.
    has_feedback: bool = False
    has_activity: bool = False
    has_community_data: bool = False
    has_problems: bool = False
    has_suggestions: bool = False
    has_questions: bool = False
    # Topics splits into two independent concepts; either alone is enough to
    # justify the page, and the page renders them as separate sections.
    has_community_topics: bool = False
    has_repository_areas: bool = False
    # "ready" | "generating" | "unavailable" | "legacy_not_generated"
    intelligence_status: str = "legacy_not_generated"

    @property
    def has_topics(self) -> bool:
        return self.has_community_topics or self.has_repository_areas


class GithubIntelligenceLink(BaseModel):
    capability: str
    available: bool


class GithubAiEvidenceRef(BaseModel):
    evidence_id: str
    title: str | None = None
    url: str | None = None
    kind: str = "repository_document"


class GithubKeyIntelligenceItem(BaseModel):
    """One supporting finding under the assessment tiles.

    Carries no recommended action by design: Top Priorities and Actionable
    Insights own actions, and repeating them here is what made the advanced
    views read as one view rendered several times.
    """

    title: str
    finding: str
    why_it_matters: str | None = None
    category: str | None = None
    evidence: list[GithubAiEvidenceRef] = []


class GithubAiAssessment(BaseModel):
    """The compact qualitative judgement, DERIVED from persisted intelligence.

    Deliberately has no score field. The underlying evidence is a bounded
    sample of documentation and community records; a number computed from
    that would carry a precision the evidence cannot support, and readers
    treat numbers as measurements.
    """

    assessment: str | None = None
    strongest_quality: str | None = None
    #: The area the strongest quality belongs to, DERIVED by the shared
    #: semantic classifier from the finding's own words -- never the model's
    #: self-reported category, which is how "Comprehensive Feature Set" came
    #: to be presented to readers as a Performance strength.
    strongest_quality_area: str | None = None
    biggest_risk: str | None = None
    biggest_risk_area: str | None = None
    attention_first: str | None = None
    maturity_statement: str | None = None
    #: Supporting detail beneath the tiles. Whatever the four fields above
    #: already used is SUBTRACTED before this is filled, so the list adds
    #: nuance rather than repeating the headline three lines later.
    key_intelligence: list[GithubKeyIntelligenceItem] = []


class GithubAiPriority(BaseModel):
    title: str
    priority_level: str
    why_it_matters: str
    what_to_do: str | None = None
    where_to_start: str | None = None
    expected_impact: str | None = None
    evidence: list[GithubAiEvidenceRef] = []


class GithubAiInsight(BaseModel):
    title: str
    category: str
    finding: str
    why_it_matters: str | None = None
    recommended_action: str | None = None
    confidence: str | None = None
    evidence: list[GithubAiEvidenceRef] = []


class GithubReadinessCategory(BaseModel):
    name: str
    #: "good" | "needs_work" | "not_enough_evidence"
    state: str
    detail: str | None = None


class GithubProductionReadiness(BaseModel):
    #: "ready" | "partially_ready" | "not_enough_evidence"
    verdict: str
    verdict_explanation: str | None = None
    categories: list[GithubReadinessCategory] = []
    blockers: list[GithubAiPriority] = []


class GithubAiViews(BaseModel):
    """The four AI subviews the secondary navigation bar switches between.

    ONE persisted Repository Intelligence synthesis, four derivations. They
    are computed here, server-side, rather than in the browser, for one
    reason that matters: the exported PDF derives them too (see
    app/services/exports/github_report.py), and a screen and a document that
    derive the same thing from the same data by two different
    implementations will eventually disagree. Both now call
    `repository_ai_views`.

    Every field is a pure function of the persisted result. Reading them
    costs no provider call and no GitHub call, which is what makes switching
    between the four tabs free -- and what lets History render them with the
    AI provider offline.
    """

    assessment: GithubAiAssessment = GithubAiAssessment()
    top_priorities: list[GithubAiPriority] = []
    actionable_insights: list[GithubAiInsight] = []
    production_readiness: GithubProductionReadiness | None = None


class GithubAnalyticsResponse(BaseModel):
    job_id: UUID
    bucket_granularity: str
    repository: GithubRepositoryHeader | None
    summary: GithubSummaryMetrics
    issue_state_distribution: list[GithubIssueStateSlice]
    issue_time_series: list[GithubTimeSeriesPoint]
    pull_request_time_series: list[GithubTimeSeriesPoint]
    top_labels: list[GithubLabelCount]
    release_timeline: list[GithubReleasePoint]
    feedback_sentiment: GithubFeedbackSentiment
    entity_composition: GithubEntityComposition
    top_contributors: list[GithubContributor]
    documentation: GithubDocumentationSummary
    intelligence_links: list[GithubIntelligenceLink]
    coverage: GithubCoverage
    # Adaptive-layout inputs (Phase 4.1). Presence of real data per section,
    # kept separate from `coverage` so the frontend can distinguish "this
    # repository genuinely has no issues" from "issues were not collected".
    activity: GithubActivityPresence = GithubActivityPresence()
    activity_narrative: GithubActivityNarrative = GithubActivityNarrative()
    maturity_signals: list[GithubMaturitySignal] = []
    glance: GithubRepositoryGlance | None = None
    # AI-synthesised repository intelligence (Phase 5), read CACHE-ONLY from
    # the row the analysis job persisted. Never generated here.
    repository_intelligence: RepositoryIntelligenceEnvelope = RepositoryIntelligenceEnvelope(
        status="legacy_not_generated"
    )
    # The four AI subviews, derived from the envelope above. Empty for every
    # status other than "ready" -- there is nothing to derive from until a
    # synthesis has actually landed.
    ai_views: GithubAiViews = GithubAiViews()
    # The four PRIMARY pages, each projected from the same persisted result
    # plus the deterministic documentation/activity facts above.
    #
    # Shipped in this one response on purpose: it is what makes navigating
    # Overview -> Repository -> Problems -> Requests cost zero requests, zero
    # generations and zero GitHub calls, and what guarantees the four pages
    # cannot disagree with each other or with the exported PDF.
    page_views: GithubPageViews = GithubPageViews()
    # Source-aware capability visibility for the View Analysis navigation.
    capabilities: GithubCapabilityAvailability = GithubCapabilityAvailability()


class WorkspaceSourceVolume(BaseModel):
    """How much of one source type the caller has analysed.

    Every field is a count of persisted rows -- completed jobs, distinct
    subjects (videos, repositories, pages, files), and the source's own
    natural unit of work. The unit differs on purpose: a YouTube analysis is
    measured in comments, a web page in findings, a dataset in rows, and
    forcing one label on all of them would make the numbers incomparable
    while looking comparable.
    """

    source_type: str
    label: str
    #: Completed analyses of this source.
    analyses: int
    #: What one analysis is OF, in the plural ("videos", "repositories").
    subject_label: str
    #: Distinct subjects analysed (a video analysed twice counts once).
    subjects: int
    #: The source's own unit of measured work ("comments analyzed", ...).
    unit_label: str
    units: int
    latest_completed_at: datetime | None = None


class WorkspaceActivityPoint(BaseModel):
    """Completed analyses in one ISO week, split by source type."""

    period_start: date
    counts: dict[str, int]
    total: int


class WorkspaceSentimentSummary(BaseModel):
    """Aggregated across every completed job the caller owns, regardless
    of source type -- deliberately source-agnostic (see module docstring).

    The sentiment/language block below is COMMENT-SHAPED: it sums the
    per-job feedback summaries, which only comment-bearing sources produce
    (YouTube, GitHub, pasted text, record-pipeline imports). Web page and
    dataset analyses have no such summary and are represented by the
    product-wide fields -- `total_analyses`, `sources`, `activity` -- which
    count every completed analysis whatever its source.
    """

    #: Completed jobs that carry a feedback summary (the sentiment block's
    #: denominator). NOT the number of analyses: see total_analyses.
    job_count: int
    #: Every completed analysis the caller owns, all sources.
    total_analyses: int = 0
    #: Per-source volumes, in product order. Always lists every source the
    #: product offers, with zeros, so an empty source is visible as empty.
    sources: list[WorkspaceSourceVolume] = []
    #: Completed analyses per ISO week, most recent last.
    activity: list[WorkspaceActivityPoint] = []
    #: The source types that contributed to the sentiment block.
    sentiment_sources: list[str] = []
    total_comments: int
    analyzed_comments: int
    positive_count: int
    negative_count: int
    neutral_count: int
    uncertain_count: int
    positive_percentage: float
    negative_percentage: float
    neutral_percentage: float
    uncertain_percentage: float
    overall_sentiment: OverallSentiment
    average_confidence: float | None
    spam_count: int
    sarcasm_count: int
    language_breakdown: LanguageBreakdown
