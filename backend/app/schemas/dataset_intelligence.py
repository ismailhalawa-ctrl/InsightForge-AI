"""API contract for Universal Dataset Intelligence.

These models are also the PERSISTENCE format: the worker serializes the
engine's dataclasses through them once, stores the result, and every read
afterwards validates the stored JSON back through the same models. One shape,
so a stored analysis and a fresh one can never differ, and a schema change is
caught at load rather than in the browser.

Sections are separate response models because they are separate reads. The
Overview page never loads column profiles or the correlation matrix, and the
Explore page pages through columns rather than returning all hundred at once.
"""

from datetime import datetime

from pydantic import BaseModel, Field

DATASET_RESPONSE_SCHEMA_VERSION = 1


class DatasetOverviewResponse(BaseModel):
    file_name: str
    file_type: str
    file_size_bytes: int | None
    source_kind: str
    row_count: int
    column_count: int
    total_cells: int
    missing_cells: int
    missing_percentage: float
    duplicate_rows: int
    sheet_name: str | None
    available_sheets: list[str]
    encoding: str | None
    delimiter: str | None
    estimated_memory_bytes: int
    type_breakdown: dict[str, int]
    role_breakdown: dict[str, int]
    warnings: list[str]


class CoverageAreaResponse(BaseModel):
    """Coverage for ONE analysis area.

    `status` is the vocabulary the UI renders: full, sampled, not_applicable
    or unavailable. The last two are distinct on purpose -- "this dataset has
    no date column" and "the temporal stage failed" are different facts and
    lead to different next steps.
    """

    area: str
    label: str
    status: str
    coverage_percentage: float | None
    analyzed: int | None
    total: int | None
    detail: str


class DatasetCoverageResponse(BaseModel):
    total_rows: int
    analyzed_rows: int
    sampled: bool
    sampling_method: str | None
    coverage_percentage: float
    duplicate_detection_complete: bool
    notes: list[str]
    # Per-area coverage. The row-level percentage above describes profiling;
    # text analysis is capped separately and is routinely much lower.
    areas: list[CoverageAreaResponse] = Field(default_factory=list)


class NumericStatisticsResponse(BaseModel):
    count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    standard_deviation: float | None
    q1: float
    q3: float
    iqr: float
    lower_bound: float
    upper_bound: float
    outlier_count: int
    outlier_percentage: float
    outlier_examples: list[float]
    histogram_bins: list[dict]


class CategoricalStatisticsResponse(BaseModel):
    distinct_count: int
    top_values: list[dict]
    dominant_value: str | None
    dominant_percentage: float
    other_count: int


class DatetimeStatisticsResponse(BaseModel):
    earliest: datetime
    latest: datetime
    range_days: int
    granularity: str
    parsed_count: int


class TextStatisticsResponse(BaseModel):
    average_length: float
    minimum_length: int
    maximum_length: int
    empty_after_strip: int
    distinct_count: int


class ColumnProfileResponse(BaseModel):
    index: int
    name: str
    technical_type: str
    semantic_role: str
    role_confidence: float
    role_reason: str
    analyzed_count: int
    non_empty_count: int
    null_count: int
    null_percentage: float
    unique_count: int
    uniqueness_ratio: float
    sample_values: list[str]
    numeric: NumericStatisticsResponse | None = None
    categorical: CategoricalStatisticsResponse | None = None
    datetime_stats: DatetimeStatisticsResponse | None = None
    text: TextStatisticsResponse | None = None
    type_mismatch_count: int = 0
    type_mismatch_examples: list[str] = Field(default_factory=list)
    numeric_unit: str | None = None


class QualityIssueResponse(BaseModel):
    issue_type: str
    severity: str
    column: str | None
    title: str
    explanation: str
    recommendation: str
    affected_count: int
    affected_percentage: float
    examples: list[str]
    score_penalty: float


class MissingConcentrationResponse(BaseModel):
    """Where the missing cells are, as shares of the total missing."""

    missing_cells: int
    columns_with_missing: int
    top_columns: list[dict]
    top_share_percentage: float
    empty_column_share_percentage: float
    empty_columns: list[str]
    populated_columns_complete: bool
    concentrated: bool


class QualityCheckResponse(BaseModel):
    check: str
    label: str
    status: str  # passed | issues_found | not_applicable
    coverage: str  # full | sampled | none
    detail: str


class QualityReportResponse(BaseModel):
    health_score: int
    health_band: str
    issues: list[QualityIssueResponse]
    counts_by_severity: dict[str, int]
    total_cells: int
    missing_cells: int
    missing_percentage: float
    duplicate_rows: int
    duplicate_row_percentage: float
    scoring_rules: list[dict]
    missing_concentration: MissingConcentrationResponse | None = None
    checks: list[QualityCheckResponse] = Field(default_factory=list)
    # Score after every DETERMINISTICALLY resolvable issue is fixed. None
    # when nothing qualifies -- never an estimate, and never model-produced.
    projected_health_score: int | None = None
    projected_health_band: str | None = None
    resolvable_penalty: float = 0.0
    resolvable_issue_types: list[str] = Field(default_factory=list)


class CleaningRecommendationResponse(BaseModel):
    action: str
    applicability: str
    column: str | None
    title: str
    reason: str
    affected_data: str
    why: str = ""
    expected_impact: str
    affected_count: int
    affected_percentage: float
    severity: str
    source_issue: str
    examples: list[str]


class CorrelationPairResponse(BaseModel):
    column_a: str
    column_b: str
    coefficient: float
    sample_size: int
    strength: str
    direction: str


class GroupDifferenceResponse(BaseModel):
    category_column: str
    metric_column: str
    groups: list[dict]
    highest_group: str
    lowest_group: str
    highest_mean: float
    lowest_mean: float
    spread_percentage: float
    overall_mean: float


class RelationshipReportResponse(BaseModel):
    analyzable: bool
    unavailable_reason: str | None
    correlation_columns: list[str]
    correlation_matrix: list[list[float | None]]
    strongest_positive: list[CorrelationPairResponse]
    strongest_negative: list[CorrelationPairResponse]
    group_differences: list[GroupDifferenceResponse]
    excluded_columns: list[dict]
    coverage_note: str | None
    disclaimer: str


class TimePointResponse(BaseModel):
    period: str
    start: datetime
    count: int
    metrics: dict[str, float]


class MetricTrendResponse(BaseModel):
    metric_column: str
    first_value: float
    last_value: float
    change_percentage: float | None
    direction: str
    peak_period: str
    peak_value: float
    trough_period: str
    trough_value: float
    first_half_mean: float
    second_half_mean: float
    period_over_period_percentage: float | None


class TemporalReportResponse(BaseModel):
    analyzable: bool
    unavailable_reason: str | None
    date_columns: list[dict]
    primary_date_column: str | None
    granularity: str | None
    earliest: datetime | None
    latest: datetime | None
    span_days: int | None
    series: list[TimePointResponse]
    volume_trend: MetricTrendResponse | None
    metric_trends: list[MetricTrendResponse]
    rows_without_date: int
    coverage_note: str | None


class TextExampleResponse(BaseModel):
    row_number: int
    excerpt: str
    sentiment: str
    confidence: float | None
    language: str


class TextColumnAnalysisResponse(BaseModel):
    column: str
    analyzed_count: int
    total_non_empty: int
    sampled: bool
    coverage_percentage: float
    average_length: float
    language_distribution: list[dict]
    sentiment_distribution: list[dict]
    dominant_sentiment: str | None
    positive_to_negative_ratio: float | None = None
    positive_examples: list[TextExampleResponse]
    negative_examples: list[TextExampleResponse]
    complaints: list[TextExampleResponse]
    requests: list[TextExampleResponse]
    themes: list[dict]
    unanalyzable_count: int
    spam_count: int


class TextIntelligenceReportResponse(BaseModel):
    analyzable: bool
    unavailable_reason: str | None
    columns: list[TextColumnAnalysisResponse]
    skipped_columns: list[dict]


class ChartSpecResponse(BaseModel):
    chart_id: str
    kind: str
    section: str
    title: str
    subtitle: str | None
    x_label: str
    y_label: str
    columns: list[str]
    data: list[dict]
    coverage_note: str | None
    meta: dict


class DatasetInsightResponse(BaseModel):
    insight_type: str
    title: str
    explanation: str
    evidence: str
    evidence_fact_ids: list[str]
    impact: str
    recommended_action: str | None
    confidence: str
    generated_by: str


class ExecutiveSummaryResponse(BaseModel):
    scope: str
    data_health: str
    strongest_findings: list[str]
    key_risks: list[str]
    recommended_actions: list[str]
    generated_by: str


class DatasetFactResponse(BaseModel):
    fact_id: str
    scope: str
    statement: str
    weight: float
    columns: list[str]
    measures: dict
    # Context for the reader and for the AI stage, never an insight on its
    # own -- see DatasetFact.context_only.
    context_only: bool = False
    category: str = ""


class DatasetInsightsResponse(BaseModel):
    insights: list[DatasetInsightResponse]
    executive_summary: ExecutiveSummaryResponse
    facts: list[DatasetFactResponse]
    generated_by: str
    provider_status: str
    provider_used: str | None
    model_used: str | None
    prompt_version: str
    unavailable_reason: str | None


class DatasetPreviewResponse(BaseModel):
    columns: list[str]
    rows: list[list[str | None]]
    note: str


class DatasetCapabilityAvailability(BaseModel):
    """Whether each result section has anything behind it.

    Mirrors GithubCapabilityAvailability/RedditCapabilityAvailability: these
    decide what a PAGE SAYS, never whether the page exists. All six dataset
    sections always render -- a section with nothing behind it shows a
    truthful empty state rather than disappearing between analyses.
    """

    has_quality_issues: bool
    has_numeric_columns: bool
    has_relationships: bool
    has_temporal: bool
    has_text: bool
    has_ai_insights: bool


class DatasetAnalysisSummaryResponse(BaseModel):
    job_id: str
    dataset_id: str | None
    schema_version: int
    source_kind: str
    file_name: str
    file_type: str
    file_size_bytes: int | None
    row_count: int
    column_count: int
    analyzed_row_count: int
    health_score: int
    missing_percentage: float
    duplicate_row_count: int
    sheet_name: str | None
    insights_generated_by: str
    analysis_duration_ms: float
    created_at: datetime


class DatasetAnalysisResponse(BaseModel):
    """The Overview payload: everything a first screen needs and nothing it
    does not. Column profiles, the correlation matrix and the chart
    specifications are served by their own endpoints."""

    summary: DatasetAnalysisSummaryResponse
    overview: DatasetOverviewResponse
    coverage: DatasetCoverageResponse
    quality_summary: dict
    executive_summary: ExecutiveSummaryResponse
    strongest_findings: list[DatasetInsightResponse]
    capabilities: DatasetCapabilityAvailability
    charts: list[ChartSpecResponse]


class DatasetColumnsResponse(BaseModel):
    columns: list[ColumnProfileResponse]
    total: int
    limit: int
    offset: int


class DatasetQualityResponse(BaseModel):
    quality: QualityReportResponse
    cleaning: list[CleaningRecommendationResponse]
    charts: list[ChartSpecResponse]


class DatasetRelationshipsResponse(BaseModel):
    relationships: RelationshipReportResponse
    charts: list[ChartSpecResponse]


class DatasetTrendsResponse(BaseModel):
    temporal: TemporalReportResponse
    charts: list[ChartSpecResponse]


class DatasetTextResponse(BaseModel):
    text: TextIntelligenceReportResponse
