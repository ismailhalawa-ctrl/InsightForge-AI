/**
 * backend/app/api/v1/dataset_analysis.py + backend/app/schemas/dataset_intelligence.py.
 *
 * Every call here is a CACHE READ of an analysis the worker already
 * computed and persisted. None of these endpoints can trigger a
 * recomputation, re-read the uploaded file, or call an AI provider -- which
 * is what makes reopening a dataset analysis from History instant.
 *
 * Sectioned to match the six result pages, so a page requests what it
 * renders and nothing else. The column profiles are paginated because a
 * 100-column upload has a hundred full statistical profiles behind it.
 */
import { apiRequest, toQueryString } from "@/lib/api-client";

export type DatasetTechnicalType =
  | "integer"
  | "float"
  | "boolean"
  | "datetime"
  | "categorical"
  | "text"
  | "empty"
  | "unknown";

export type DatasetSemanticRole =
  | "identifier"
  | "numeric_metric"
  | "currency"
  | "percentage"
  | "categorical_dimension"
  | "datetime_dimension"
  | "free_text"
  | "email"
  | "url"
  | "geographic"
  | "boolean_flag"
  | "unknown";

export type DatasetQualitySeverity = "critical" | "high" | "medium" | "low";

export type DatasetChartKind =
  | "histogram"
  | "box_plot"
  | "bar"
  | "line"
  | "scatter"
  | "heatmap"
  | "stacked_bar";

export type DatasetChartSection =
  | "overview"
  | "quality"
  | "explore"
  | "relationships"
  | "trends";

export type DatasetChartSpec = {
  chart_id: string;
  kind: DatasetChartKind;
  section: DatasetChartSection;
  title: string;
  subtitle: string | null;
  x_label: string;
  y_label: string;
  columns: string[];
  data: Record<string, unknown>[];
  /** Set whenever the chart shows less than the whole picture (capped
   * categories, downsampled scatter). Always rendered -- a truncated chart
   * that does not say so is a wrong chart. */
  coverage_note: string | null;
  meta: Record<string, unknown>;
};

export type DatasetOverview = {
  file_name: string;
  file_type: string;
  file_size_bytes: number | null;
  source_kind: string;
  row_count: number;
  column_count: number;
  total_cells: number;
  missing_cells: number;
  missing_percentage: number;
  duplicate_rows: number;
  sheet_name: string | null;
  available_sheets: string[];
  encoding: string | null;
  delimiter: string | null;
  estimated_memory_bytes: number;
  type_breakdown: Record<string, number>;
  role_breakdown: Record<string, number>;
  warnings: string[];
};

/** full / sampled are measured; not_applicable and unavailable are
 * deliberately distinct -- "this dataset has no date column" and "the
 * temporal stage failed" lead to different next steps. */
export type DatasetCoverageStatus = "full" | "sampled" | "not_applicable" | "unavailable";

export type DatasetCoverageArea = {
  area: string;
  label: string;
  status: DatasetCoverageStatus;
  coverage_percentage: number | null;
  analyzed: number | null;
  total: number | null;
  detail: string;
};

export type DatasetCoverage = {
  total_rows: number;
  analyzed_rows: number;
  sampled: boolean;
  sampling_method: string | null;
  coverage_percentage: number;
  duplicate_detection_complete: boolean;
  notes: string[];
  /** Per-area coverage. The row-level percentage above describes profiling
   * only; text analysis is capped separately and is routinely far lower. */
  areas: DatasetCoverageArea[];
};

export type DatasetNumericStatistics = {
  count: number;
  minimum: number;
  maximum: number;
  mean: number;
  median: number;
  standard_deviation: number | null;
  q1: number;
  q3: number;
  iqr: number;
  lower_bound: number;
  upper_bound: number;
  outlier_count: number;
  outlier_percentage: number;
  outlier_examples: number[];
  histogram_bins: { start: number; end: number; count: number }[];
};

export type DatasetCategoricalStatistics = {
  distinct_count: number;
  top_values: { value: string; count: number; percentage: number }[];
  dominant_value: string | null;
  dominant_percentage: number;
  other_count: number;
};

export type DatasetDatetimeStatistics = {
  earliest: string;
  latest: string;
  range_days: number;
  granularity: string;
  parsed_count: number;
};

export type DatasetTextStatistics = {
  average_length: number;
  minimum_length: number;
  maximum_length: number;
  empty_after_strip: number;
  distinct_count: number;
};

export type DatasetColumnProfile = {
  index: number;
  name: string;
  technical_type: DatasetTechnicalType;
  semantic_role: DatasetSemanticRole;
  role_confidence: number;
  /** Why this role was assigned. Shown in the UI: a role with no stated
   * basis is indistinguishable from a guess. */
  role_reason: string;
  analyzed_count: number;
  non_empty_count: number;
  null_count: number;
  null_percentage: number;
  unique_count: number;
  uniqueness_ratio: number;
  sample_values: string[];
  numeric: DatasetNumericStatistics | null;
  categorical: DatasetCategoricalStatistics | null;
  datetime_stats: DatasetDatetimeStatistics | null;
  text: DatasetTextStatistics | null;
  type_mismatch_count: number;
  type_mismatch_examples: string[];
  numeric_unit: string | null;
};

export type DatasetQualityIssue = {
  issue_type: string;
  severity: DatasetQualitySeverity;
  column: string | null;
  title: string;
  explanation: string;
  recommendation: string;
  affected_count: number;
  affected_percentage: number;
  examples: string[];
  /** This issue's contribution to the health score, so the page can show
   * why the number is what it is. */
  score_penalty: number;
};

export type DatasetMissingConcentration = {
  missing_cells: number;
  columns_with_missing: number;
  top_columns: {
    column: string;
    missing_count: number;
    analyzed_rows?: number;
    missing_percentage_of_column: number;
    /** This column's share OF THE TOTAL MISSING, not of its own column. */
    share_of_missing: number;
    entirely_empty: boolean;
  }[];
  top_share_percentage: number;
  empty_column_share_percentage: number;
  empty_columns: string[];
  populated_columns_complete: boolean;
  concentrated: boolean;
};

export type DatasetQualityCheck = {
  check: string;
  label: string;
  status: "passed" | "issues_found" | "not_applicable";
  coverage: "full" | "sampled" | "none";
  detail: string;
};

export type DatasetQualityReport = {
  health_score: number;
  /** Stored label. The UI derives its own from the score -- see
   * lib/dataset-health -- so analyses persisted under an older mapping
   * still display consistently. */
  health_band: string;
  issues: DatasetQualityIssue[];
  counts_by_severity: Record<string, number>;
  total_cells: number;
  missing_cells: number;
  missing_percentage: number;
  duplicate_rows: number;
  duplicate_row_percentage: number;
  scoring_rules: { issue_type: string; max_penalty: number; applied: number }[];
  missing_concentration: DatasetMissingConcentration | null;
  checks: DatasetQualityCheck[];
  /** Score once every deterministically resolvable issue is fixed. Null when
   * nothing qualifies -- never an estimate, never model-produced. */
  projected_health_score: number | null;
  projected_health_band: string | null;
  resolvable_penalty: number;
  resolvable_issue_types: string[];
};

export type DatasetCleaningRecommendation = {
  action: string;
  applicability: "safe" | "review" | "manual";
  column: string | null;
  title: string;
  reason: string;
  affected_data: string;
  why?: string;
  expected_impact: string;
  affected_count: number;
  affected_percentage: number;
  severity: DatasetQualitySeverity;
  source_issue: string;
  examples: string[];
};

export type DatasetCorrelationPair = {
  column_a: string;
  column_b: string;
  coefficient: number;
  sample_size: number;
  strength: string;
  direction: "positive" | "negative";
};

export type DatasetGroupDifference = {
  category_column: string;
  metric_column: string;
  groups: {
    value: string;
    count: number;
    mean: number;
    share_of_rows: number;
    difference_from_overall_percentage: number;
  }[];
  highest_group: string;
  lowest_group: string;
  highest_mean: number;
  lowest_mean: number;
  spread_percentage: number;
  overall_mean: number;
};

export type DatasetRelationshipReport = {
  analyzable: boolean;
  unavailable_reason: string | null;
  correlation_columns: string[];
  correlation_matrix: (number | null)[][];
  strongest_positive: DatasetCorrelationPair[];
  strongest_negative: DatasetCorrelationPair[];
  group_differences: DatasetGroupDifference[];
  excluded_columns: { column: string; reason: string }[];
  coverage_note: string | null;
  disclaimer: string;
};

export type DatasetTimePoint = {
  period: string;
  start: string;
  count: number;
  metrics: Record<string, number>;
};

export type DatasetMetricTrend = {
  metric_column: string;
  first_value: number;
  last_value: number;
  change_percentage: number | null;
  direction: string;
  peak_period: string;
  peak_value: number;
  trough_period: string;
  trough_value: number;
  first_half_mean: number;
  second_half_mean: number;
  period_over_period_percentage: number | null;
};

export type DatasetTemporalReport = {
  analyzable: boolean;
  unavailable_reason: string | null;
  date_columns: {
    column: string;
    earliest: string | null;
    latest: string | null;
    range_days: number;
    granularity: string;
    null_percentage: number;
  }[];
  primary_date_column: string | null;
  granularity: string | null;
  earliest: string | null;
  latest: string | null;
  span_days: number | null;
  series: DatasetTimePoint[];
  volume_trend: DatasetMetricTrend | null;
  metric_trends: DatasetMetricTrend[];
  rows_without_date: number;
  coverage_note: string | null;
};

export type DatasetTextExample = {
  row_number: number;
  excerpt: string;
  sentiment: string;
  confidence: number | null;
  language: string;
};

export type DatasetTextColumnAnalysis = {
  column: string;
  analyzed_count: number;
  total_non_empty: number;
  sampled: boolean;
  coverage_percentage: number;
  average_length: number;
  language_distribution: { language: string; count: number; percentage: number }[];
  sentiment_distribution: { sentiment: string; count: number; percentage: number }[];
  dominant_sentiment: string | null;
  /** positive/negative, only when BOTH are present. */
  positive_to_negative_ratio: number | null;
  positive_examples: DatasetTextExample[];
  negative_examples: DatasetTextExample[];
  complaints: DatasetTextExample[];
  requests: DatasetTextExample[];
  themes: { term: string; occurrences: number; rows: number; share_of_rows: number }[];
  unanalyzable_count: number;
  spam_count: number;
};

export type DatasetTextReport = {
  analyzable: boolean;
  unavailable_reason: string | null;
  columns: DatasetTextColumnAnalysis[];
  skipped_columns: { column: string; reason: string }[];
};

export type DatasetInsight = {
  insight_type: string;
  title: string;
  explanation: string;
  evidence: string;
  /** Ids of the measured facts this insight rests on. An insight with an
   * empty array never reaches the client -- the backend discards it. */
  evidence_fact_ids: string[];
  impact: string;
  recommended_action: string | null;
  confidence: string;
  generated_by: "ai" | "deterministic";
};

export type DatasetExecutiveSummary = {
  scope: string;
  data_health: string;
  strongest_findings: string[];
  key_risks: string[];
  recommended_actions: string[];
  generated_by: "ai" | "deterministic";
};

export type DatasetFact = {
  fact_id: string;
  scope: string;
  statement: string;
  weight: number;
  columns: string[];
  measures: Record<string, unknown>;
  /** Context for the reader, never an insight on its own. */
  context_only: boolean;
};

export type DatasetCapabilityAvailability = {
  has_quality_issues: boolean;
  has_numeric_columns: boolean;
  has_relationships: boolean;
  has_temporal: boolean;
  has_text: boolean;
  has_ai_insights: boolean;
};

export type DatasetAnalysisSummary = {
  job_id: string;
  dataset_id: string | null;
  schema_version: number;
  source_kind: string;
  file_name: string;
  file_type: string;
  file_size_bytes: number | null;
  row_count: number;
  column_count: number;
  analyzed_row_count: number;
  health_score: number;
  missing_percentage: number;
  duplicate_row_count: number;
  sheet_name: string | null;
  insights_generated_by: string;
  analysis_duration_ms: number;
  created_at: string;
};

export type DatasetAnalysisResponse = {
  summary: DatasetAnalysisSummary;
  overview: DatasetOverview;
  coverage: DatasetCoverage;
  quality_summary: {
    health_score: number;
    health_band: string;
    counts_by_severity: Record<string, number>;
    issue_count: number;
    missing_percentage: number;
    duplicate_rows: number;
    /** Carried on the Overview so the concentration insight and the
     * projected score render without a second request. */
    missing_concentration: DatasetMissingConcentration | null;
    projected_health_score: number | null;
    projected_health_band: string | null;
  };
  executive_summary: DatasetExecutiveSummary;
  strongest_findings: DatasetInsight[];
  capabilities: DatasetCapabilityAvailability;
  charts: DatasetChartSpec[];
};

export type DatasetColumnsResponse = {
  columns: DatasetColumnProfile[];
  total: number;
  limit: number;
  offset: number;
};

export type DatasetQualityResponse = {
  quality: DatasetQualityReport;
  cleaning: DatasetCleaningRecommendation[];
  charts: DatasetChartSpec[];
};

export type DatasetRelationshipsResponse = {
  relationships: DatasetRelationshipReport;
  charts: DatasetChartSpec[];
};

export type DatasetTrendsResponse = {
  temporal: DatasetTemporalReport;
  charts: DatasetChartSpec[];
};

export type DatasetTextResponse = { text: DatasetTextReport };

export type DatasetInsightsResponse = {
  insights: DatasetInsight[];
  executive_summary: DatasetExecutiveSummary;
  facts: DatasetFact[];
  generated_by: "ai" | "deterministic";
  provider_status: string;
  provider_used: string | null;
  model_used: string | null;
  prompt_version: string;
  /** Present when the AI provider could not be used. The insights below are
   * still real -- computed directly from the dataset -- and this explains
   * why they were not synthesised. */
  unavailable_reason: string | null;
};

export type DatasetPreviewResponse = {
  columns: string[];
  rows: (string | null)[][];
  note: string;
};

export function getDatasetAnalysis(
  accessToken: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<DatasetAnalysisResponse> {
  return apiRequest<DatasetAnalysisResponse>(
    `/analysis/jobs/${jobId}/dataset`,
    { method: "GET", signal },
    accessToken,
  );
}

export function getDatasetColumns(
  accessToken: string,
  jobId: string,
  params: { limit?: number; offset?: number; search?: string } = {},
  signal?: AbortSignal,
): Promise<DatasetColumnsResponse> {
  return apiRequest<DatasetColumnsResponse>(
    `/analysis/jobs/${jobId}/dataset/columns${toQueryString(params)}`,
    { method: "GET", signal },
    accessToken,
  );
}

export function getDatasetQuality(
  accessToken: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<DatasetQualityResponse> {
  return apiRequest<DatasetQualityResponse>(
    `/analysis/jobs/${jobId}/dataset/quality`,
    { method: "GET", signal },
    accessToken,
  );
}

export function getDatasetRelationships(
  accessToken: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<DatasetRelationshipsResponse> {
  return apiRequest<DatasetRelationshipsResponse>(
    `/analysis/jobs/${jobId}/dataset/relationships`,
    { method: "GET", signal },
    accessToken,
  );
}

export function getDatasetTrends(
  accessToken: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<DatasetTrendsResponse> {
  return apiRequest<DatasetTrendsResponse>(
    `/analysis/jobs/${jobId}/dataset/trends`,
    { method: "GET", signal },
    accessToken,
  );
}

export function getDatasetText(
  accessToken: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<DatasetTextResponse> {
  return apiRequest<DatasetTextResponse>(
    `/analysis/jobs/${jobId}/dataset/text`,
    { method: "GET", signal },
    accessToken,
  );
}

export function getDatasetInsights(
  accessToken: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<DatasetInsightsResponse> {
  return apiRequest<DatasetInsightsResponse>(
    `/analysis/jobs/${jobId}/dataset/insights`,
    { method: "GET", signal },
    accessToken,
  );
}

export function getDatasetPreview(
  accessToken: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<DatasetPreviewResponse> {
  return apiRequest<DatasetPreviewResponse>(
    `/analysis/jobs/${jobId}/dataset/preview`,
    { method: "GET", signal },
    accessToken,
  );
}
