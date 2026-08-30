import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  DatasetInsightsPage,
  DatasetOverviewPage,
  DatasetQualityPage,
  DatasetRelationshipsPage,
  DatasetTextPanel,
  DatasetTrendsPage,
} from "./dataset-page-views";
import { DatasetChart } from "./dataset-charts";
import {
  DATASET_NAV_ITEMS,
  datasetNavHref,
  datasetSectionHasData,
  visibleDatasetNavItems,
} from "@/config/dataset-nav";
import { translations } from "@/lib/i18n/translations";
import type {
  DatasetAnalysisResponse,
  DatasetCapabilityAvailability,
  DatasetChartSpec,
  DatasetInsightsResponse,
  DatasetQualityResponse,
  DatasetRelationshipsResponse,
  DatasetTextReport,
  DatasetTrendsResponse,
} from "@/lib/api/dataset-analysis";

vi.mock("@/lib/i18n/language-context", () => ({
  useLanguage: () => ({
    language: "en",
    dir: "ltr",
    t: (ns: string, key: string) => {
      const dictionaries = translations as unknown as Record<
        string,
        Record<string, Record<string, string> | undefined> | undefined
      >;
      return dictionaries.en?.[ns]?.[key] ?? key;
    },
  }),
}));

// recharts measures its container, which jsdom reports as 0x0 -- every
// ResponsiveContainer would render nothing and the tests would assert on an
// empty tree. A fixed size makes the charts render deterministically.
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 600, height: 300 }}>{children}</div>
    ),
  };
});

// ---- fixtures ------------------------------------------------------------

const CAPABILITIES: DatasetCapabilityAvailability = {
  has_quality_issues: true,
  has_numeric_columns: true,
  has_relationships: true,
  has_temporal: true,
  has_text: true,
  has_ai_insights: true,
};

const OVERVIEW: DatasetAnalysisResponse = {
  summary: {
    job_id: "job-1",
    dataset_id: "ds-1",
    schema_version: 1,
    source_kind: "file_upload",
    file_name: "customers.csv",
    file_type: "csv",
    file_size_bytes: 48231,
    row_count: 1203,
    column_count: 7,
    analyzed_row_count: 1203,
    health_score: 82,
    missing_percentage: 4.2,
    duplicate_row_count: 12,
    sheet_name: null,
    insights_generated_by: "deterministic",
    analysis_duration_ms: 412,
    created_at: "2026-08-28T10:00:00Z",
  },
  overview: {
    file_name: "customers.csv",
    file_type: "csv",
    file_size_bytes: 48231,
    source_kind: "file_upload",
    row_count: 1203,
    column_count: 7,
    total_cells: 70326,
    missing_cells: 15628,
    missing_percentage: 22.2,
    duplicate_rows: 12,
    sheet_name: null,
    available_sheets: [],
    encoding: "utf-8",
    delimiter: ",",
    estimated_memory_bytes: 512000,
    type_breakdown: { integer: 2, categorical: 2, text: 1, datetime: 1, empty: 1 },
    role_breakdown: { identifier: 1, numeric_metric: 1 },
    warnings: [],
  },
  coverage: {
    total_rows: 1203,
    analyzed_rows: 1203,
    sampled: false,
    sampling_method: null,
    coverage_percentage: 100,
    duplicate_detection_complete: true,
    notes: [],
    areas: [
      {
        area: "structural",
        label: "Structural profiling",
        status: "full",
        coverage_percentage: 100,
        analyzed: 1203,
        total: 1203,
        detail: "Column types, roles and statistics",
      },
      {
        area: "text",
        label: "Text / NLP intelligence",
        status: "sampled",
        coverage_percentage: 25,
        analyzed: 300,
        total: 1203,
        detail: "feedback",
      },
      {
        area: "temporal",
        label: "Temporal analysis",
        status: "not_applicable",
        coverage_percentage: null,
        analyzed: null,
        total: null,
        detail: "No usable date column",
      },
    ],
  },
  quality_summary: {
    health_score: 76,
    health_band: "good",
    counts_by_severity: { critical: 0, high: 1, medium: 2, low: 3 },
    issue_count: 6,
    missing_percentage: 22.2,
    duplicate_rows: 12,
    missing_concentration: {
      missing_cells: 15628,
      columns_with_missing: 2,
      top_columns: [
        {
          column: "rating",
          missing_count: 7814,
          analyzed_rows: 7814,
          missing_percentage_of_column: 100,
          share_of_missing: 50,
          entirely_empty: true,
        },
        {
          column: "language",
          missing_count: 7814,
          analyzed_rows: 7814,
          missing_percentage_of_column: 100,
          share_of_missing: 50,
          entirely_empty: true,
        },
      ],
      top_share_percentage: 100,
      empty_column_share_percentage: 100,
      empty_columns: ["rating", "language"],
      populated_columns_complete: true,
      concentrated: true,
    },
    projected_health_score: 100,
    projected_health_band: "excellent",
  },
  executive_summary: {
    scope: "1,203 rows across 7 columns, uploaded as customers.csv.",
    data_health:
      "The dataset has a health score of 76/100 (Fair); 22.2% of cells are empty.",
    strongest_findings: [
      "The dataset holds 1,203 rows across 7 columns (70,326 cells in total).",
      "All 15,628 missing cells (22.2% of the dataset) come from 2 completely empty column(s): 'rating', 'language'.",
      "Most analyzed responses in 'feedback' are neutral: 66.2% of the analyzed sample was classified as neutral. Based on 300 of 1,203 text rows (25% coverage, systematic sample).",
      "Enterprise customers spend 24% more than the dataset average.",
    ],
    key_risks: ["14.7% of customer_age values are missing."],
    recommended_actions: ["De-duplicate before aggregating."],
    generated_by: "deterministic",
  },
  strongest_findings: [
    {
      insight_type: "segment_difference",
      title: "Enterprise spends more",
      explanation: "Enterprise customers averaged 240 against an overall average of 96.",
      evidence: "Enterprise mean 240 vs overall 96",
      evidence_fact_ids: ["f1"],
      impact: "The overall average hides this gap.",
      recommended_action: null,
      confidence: "high",
      generated_by: "deterministic",
    },
  ],
  capabilities: CAPABILITIES,
  charts: [],
};

const QUALITY: DatasetQualityResponse = {
  quality: {
    health_score: 82,
    health_band: "good",
    issues: [
      {
        issue_type: "missing_values",
        severity: "high",
        column: "customer_age",
        title: "'customer_age' is 14.7% missing",
        explanation: "177 of 1,203 rows have no value in 'customer_age'.",
        recommendation: "Investigate why these rows are blank before using this column.",
        affected_count: 177,
        affected_percentage: 14.7,
        examples: [],
        score_penalty: 2.94,
      },
      {
        issue_type: "empty_column",
        severity: "high",
        column: "legacy_code",
        title: "'legacy_code' is completely empty",
        explanation: "All 1,203 rows are empty in 'legacy_code'.",
        recommendation: "Remove the column or populate it at the source.",
        affected_count: 1203,
        affected_percentage: 100,
        examples: [],
        score_penalty: 12,
      },
    ],
    counts_by_severity: { critical: 0, high: 2, medium: 0, low: 0 },
    total_cells: 8421,
    missing_cells: 354,
    missing_percentage: 4.2,
    duplicate_rows: 12,
    duplicate_row_percentage: 1,
    scoring_rules: [
      { issue_type: "missing_values", max_penalty: 20, applied: 2.94 },
      { issue_type: "duplicate_rows", max_penalty: 15, applied: 0 },
    ],
    missing_concentration: {
      missing_cells: 354,
      columns_with_missing: 1,
      top_columns: [
        {
          column: "customer_age",
          missing_count: 177,
          analyzed_rows: 1203,
          missing_percentage_of_column: 14.7,
          share_of_missing: 100,
          entirely_empty: false,
        },
      ],
      top_share_percentage: 100,
      empty_column_share_percentage: 0,
      empty_columns: [],
      populated_columns_complete: false,
      concentrated: true,
    },
    checks: [
      {
        check: "duplicate_rows",
        label: "Duplicate rows",
        status: "passed",
        coverage: "full",
        detail: "No duplicate rows detected",
      },
      {
        check: "date_validity",
        label: "Date validity",
        status: "not_applicable",
        coverage: "none",
        detail: "No date column to check",
      },
      {
        check: "missing_values",
        label: "Missing values",
        status: "issues_found",
        coverage: "full",
        detail: "1 issue(s) found",
      },
    ],
    projected_health_score: 90,
    projected_health_band: "excellent",
    resolvable_penalty: 8,
    resolvable_issue_types: ["duplicate_rows"],
  },
  cleaning: [
    {
      action: "fill_or_drop_missing",
      applicability: "review",
      column: "customer_age",
      title: "Decide how to handle missing values in 'customer_age'",
      reason: "177 of 1,203 rows have no value in 'customer_age'.",
      affected_data: "177 values in 'customer_age'",
      expected_impact: "Statistics on this column would be computed over a stated population.",
      affected_count: 177,
      affected_percentage: 14.7,
      severity: "high",
      source_issue: "missing_values",
      examples: [],
    },
    {
      action: "drop_column",
      applicability: "safe",
      column: "legacy_code",
      title: "Remove 'legacy_code'",
      reason: "All 1,203 rows are empty in 'legacy_code'.",
      affected_data: "1,203 values in 'legacy_code'",
      why: "The column holds no values, so nothing downstream can read anything from it.",
      expected_impact: "No analysis would lose information -- this column carries none.",
      affected_count: 1203,
      affected_percentage: 100,
      severity: "high",
      source_issue: "empty_column",
      examples: [],
    },
  ],
  charts: [],
};

const RELATIONSHIPS: DatasetRelationshipsResponse = {
  relationships: {
    analyzable: true,
    unavailable_reason: null,
    correlation_columns: ["age", "monthly_spend"],
    correlation_matrix: [
      [1, 0.62],
      [0.62, 1],
    ],
    strongest_positive: [
      {
        column_a: "age",
        column_b: "monthly_spend",
        coefficient: 0.62,
        sample_size: 1180,
        strength: "moderate",
        direction: "positive",
      },
    ],
    strongest_negative: [],
    group_differences: [
      {
        category_column: "subscription",
        metric_column: "monthly_spend",
        groups: [
          {
            value: "enterprise",
            count: 400,
            mean: 240,
            share_of_rows: 33.3,
            difference_from_overall_percentage: 150,
          },
          {
            value: "free",
            count: 401,
            mean: 0,
            share_of_rows: 33.4,
            difference_from_overall_percentage: -100,
          },
        ],
        highest_group: "enterprise",
        lowest_group: "free",
        highest_mean: 240,
        lowest_mean: 0,
        spread_percentage: 0,
        overall_mean: 96,
      },
    ],
    excluded_columns: [{ column: "customer_id", reason: "Column is constant" }],
    coverage_note: null,
    disclaimer:
      "Correlation measures how two columns move together. It does not show that one causes the other, and a third factor present in neither column can produce a strong relationship between them.",
  },
  charts: [],
};

const TRENDS_PRESENT: DatasetTrendsResponse = {
  temporal: {
    analyzable: true,
    unavailable_reason: null,
    date_columns: [],
    primary_date_column: "created_at",
    granularity: "month",
    earliest: "2024-01-01T00:00:00",
    latest: "2024-07-01T00:00:00",
    span_days: 182,
    series: [
      { period: "2024-01", start: "2024-01-01T00:00:00", count: 100, metrics: { spend: 90 } },
      { period: "2024-02", start: "2024-02-01T00:00:00", count: 140, metrics: { spend: 110 } },
      { period: "2024-03", start: "2024-03-01T00:00:00", count: 180, metrics: { spend: 130 } },
    ],
    volume_trend: {
      metric_column: "row_count",
      first_value: 100,
      last_value: 180,
      change_percentage: 80,
      direction: "rising",
      peak_period: "2024-03",
      peak_value: 180,
      trough_period: "2024-01",
      trough_value: 100,
      first_half_mean: 100,
      second_half_mean: 160,
      period_over_period_percentage: 60,
    },
    metric_trends: [],
    rows_without_date: 0,
    coverage_note: null,
  },
  charts: [],
};

const TRENDS_ABSENT: DatasetTrendsResponse = {
  temporal: {
    analyzable: false,
    unavailable_reason:
      "No reliable temporal dimension was detected in this dataset. Trend analysis needs at least one column whose values parse as dates or timestamps.",
    date_columns: [],
    primary_date_column: null,
    granularity: null,
    earliest: null,
    latest: null,
    span_days: null,
    series: [],
    volume_trend: null,
    metric_trends: [],
    rows_without_date: 0,
    coverage_note: null,
  },
  charts: [],
};

const INSIGHTS: DatasetInsightsResponse = {
  insights: [
    {
      insight_type: "data_quality_risk",
      title: "Missing ages weaken every age-based statistic",
      explanation: "14.7% of customer_age values are missing and 12 duplicate rows were detected.",
      evidence: "177 of 1,203 rows are blank in customer_age.",
      evidence_fact_ids: ["f2"],
      impact: "Any average over this column silently excludes those rows.",
      recommended_action: "Decide whether to impute or drop them before reporting.",
      confidence: "high",
      generated_by: "deterministic",
    },
  ],
  executive_summary: OVERVIEW.executive_summary,
  facts: [
    {
      fact_id: "f2",
      scope: "data_quality_risk",
      statement: "177 of 1,203 rows have no value in 'customer_age'.",
      weight: 80,
      columns: ["customer_age"],
      measures: {},
      context_only: false,
    },
  ],
  generated_by: "deterministic",
  provider_status: "disabled",
  provider_used: null,
  model_used: null,
  prompt_version: "dataset-insights-v1",
  unavailable_reason: "AI insight generation is disabled for this deployment.",
};

const TEXT_PRESENT: DatasetTextReport = {
  analyzable: true,
  unavailable_reason: null,
  columns: [
    {
      column: "feedback",
      analyzed_count: 500,
      total_non_empty: 1203,
      sampled: true,
      coverage_percentage: 41.6,
      average_length: 82,
      language_distribution: [{ language: "en", count: 500, percentage: 100 }],
      sentiment_distribution: [
        { sentiment: "positive", count: 300, percentage: 60 },
        { sentiment: "negative", count: 200, percentage: 40 },
      ],
      dominant_sentiment: "positive",
      positive_to_negative_ratio: 1.5,
      positive_examples: [
        { row_number: 3, excerpt: "The dashboard is genuinely useful.", sentiment: "positive", confidence: 0.9, language: "en" },
      ],
      negative_examples: [],
      complaints: [],
      requests: [],
      themes: [{ term: "dashboard", occurrences: 120, rows: 100, share_of_rows: 20 }],
      unanalyzable_count: 0,
      spam_count: 0,
    },
  ],
  skipped_columns: [{ column: "customer_id", reason: "Values average 4 characters" }],
};

const TEXT_ABSENT: DatasetTextReport = {
  analyzable: false,
  unavailable_reason:
    "No free-text column was detected in this dataset. Identifiers, category labels, emails, URLs and dates are deliberately excluded from text analysis.",
  columns: [],
  skipped_columns: [],
};

// ---- navigation ----------------------------------------------------------

describe("dataset navigation", () => {
  it("always renders all six sections, in product order", () => {
    expect(visibleDatasetNavItems(CAPABILITIES).map((item) => item.id)).toEqual([
      "overview",
      "data-quality",
      "explore",
      "relationships",
      "trends",
      "dataset-insights",
    ]);
  });

  it("does not hide a section that has no data", () => {
    const empty: DatasetCapabilityAvailability = {
      has_quality_issues: false,
      has_numeric_columns: false,
      has_relationships: false,
      has_temporal: false,
      has_text: false,
      has_ai_insights: false,
    };
    expect(visibleDatasetNavItems(empty)).toHaveLength(6);
    // Availability decides what a PAGE SAYS, never whether it exists.
    expect(datasetSectionHasData("trends", empty)).toBe(false);
    expect(datasetSectionHasData("overview", empty)).toBe(true);
  });

  it("renders nothing until availability lands, rather than a wrong set", () => {
    expect(visibleDatasetNavItems(null)).toEqual([]);
    expect(visibleDatasetNavItems(undefined)).toEqual([]);
  });

  it("routes Overview to the analysis page and every other section to its own route", () => {
    const [overview, quality] = DATASET_NAV_ITEMS;
    expect(datasetNavHref(overview!, "job-1")).toBe("/app/analyses/job-1");
    expect(datasetNavHref(quality!, "job-1")).toBe("/app/analyses/job-1/data-quality");
  });

  it("has a translation for every label key in both locales", () => {
    for (const item of DATASET_NAV_ITEMS) {
      expect(translations.en.insights).toHaveProperty(item.labelKey);
      expect(translations.ar.insights).toHaveProperty(item.labelKey);
    }
  });
});

// ---- pages ---------------------------------------------------------------

describe("DatasetOverviewPage", () => {
  it("shows dataset identity, health and coverage from persisted values", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);

    expect(screen.getAllByText("customers.csv").length).toBeGreaterThan(0);
    expect(screen.getByText("1,203")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("76/100")).toBeInTheDocument();
    expect(screen.getAllByText("22.2%").length).toBeGreaterThan(0);
  });

  it("labels 76/100 as Fair, not Good", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    expect(screen.getAllByText("Fair").length).toBeGreaterThan(0);
    expect(screen.queryByText("Good")).not.toBeInTheDocument();
  });

  it("names the column roles rather than only the storage types", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    expect(screen.getByText("Column roles")).toBeInTheDocument();
    expect(screen.getByText("1 identifier")).toBeInTheDocument();
    expect(screen.getByText("1 numeric metric")).toBeInTheDocument();
    expect(screen.getByText(/describe how the values are stored/)).toBeInTheDocument();
  });

  it("reports per-area coverage, and never implies 100% for a sampled area", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    expect(screen.getAllByText("Analysis coverage").length).toBe(1);
    expect(screen.getByText("Text / NLP intelligence")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getAllByText("Sampled").length).toBeGreaterThan(0);
    expect(screen.getByText("Not applicable")).toBeInTheDocument();
    expect(
      screen.getByText(/300 of 1,203 rows analyzed .* 25% coverage .* systematic sample/),
    ).toBeInTheDocument();
  });

  it("contextualises the missing percentage as concentrated in empty columns", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    expect(
      screen.getAllByText(/All missing data comes from 2 completely empty columns/).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText(/Every remaining column is fully populated/).length).toBeGreaterThan(
      0,
    );
  });

  it("shows the projected health score when one was computed", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    expect(screen.getByText("After recommended fixes")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  it("renders the executive summary, the strongest findings and the actions", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    expect(
      screen.getByText("1,203 rows across 7 columns, uploaded as customers.csv."),
    ).toBeInTheDocument();
    expect(screen.getByText("Enterprise spends more")).toBeInTheDocument();
    expect(screen.getByText("Recommended actions")).toBeInTheDocument();
    expect(screen.getByText("De-duplicate before aggregating.")).toBeInTheDocument();
  });

  it("states sampling coverage rather than implying a full analysis", () => {
    const sampled: DatasetAnalysisResponse = {
      ...OVERVIEW,
      coverage: {
        ...OVERVIEW.coverage,
        analyzed_rows: 100,
        sampled: true,
        sampling_method: "systematic_every_nth",
        coverage_percentage: 8.3,
        notes: ["Profiled 100 of 1,203 rows (every 12th row)."],
      },
    };
    render(<DatasetOverviewPage data={sampled} />);
    expect(screen.getByText("Analysis coverage")).toBeInTheDocument();
    expect(screen.getByText("Coverage notes")).toBeInTheDocument();
    expect(screen.getByText(/Profiled 100 of 1,203 rows/)).toBeInTheDocument();
    expect(screen.getByText(/300 of 1,203 rows analyzed/)).toBeInTheDocument();
    expect(screen.getAllByText("Sampled").length).toBeGreaterThan(0);
  });

  it("shows a multi-sheet warning when the backend attached one", () => {
    const workbook: DatasetAnalysisResponse = {
      ...OVERVIEW,
      overview: {
        ...OVERVIEW.overview,
        file_type: "xlsx",
        sheet_name: "Q3",
        available_sheets: ["Q3", "Q4"],
        warnings: ["This workbook has 2 sheets (Q3, Q4). Only 'Q3' was analyzed."],
      },
    };
    render(<DatasetOverviewPage data={workbook} />);
    expect(screen.getByText(/Only 'Q3' was analyzed/)).toBeInTheDocument();
  });
});

describe("DatasetQualityPage", () => {
  it("states each issue once as a diagnosis, and the action separately", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(screen.getByText("'customer_age' is 14.7% missing")).toBeInTheDocument();
    // Diagnosis belongs to Detected Issues and the action to Cleaning
    // Recommendations -- the same sentence must not appear in both.
    expect(
      screen.getAllByText("177 of 1,203 rows have no value in 'customer_age'."),
    ).toHaveLength(1);
    expect(
      screen.getByText("Decide how to handle missing values in 'customer_age'"),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/^Decision:/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Needs a decision").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Safe to apply/)).not.toBeInTheDocument();
  });

  it("labels the health score with the shared band mapping", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(screen.getAllByText("Good").length).toBeGreaterThan(0);
  });

  it("lists what to fix first, ranked by recovered score", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(screen.getByText("What to fix first")).toBeInTheDocument();
    expect(screen.getByText("recovers 2.94 points")).toBeInTheDocument();
  });

  it("writes missing counts out rather than leaving them to a bar", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(screen.getByText("Where the problems are")).toBeInTheDocument();
    expect(screen.getAllByText(/177 \/ 1,203 missing/).length).toBeGreaterThan(0);
  });

  it("shows severity as a compact row when only one level is present", () => {
    const single: DatasetQualityResponse = {
      ...QUALITY,
      quality: {
        ...QUALITY.quality,
        counts_by_severity: { critical: 0, high: 1, medium: 0, low: 0 },
      },
      charts: [],
    };
    render(<DatasetQualityPage data={single} />);
    // Four labelled counters, no chart for a single bar.
    for (const level of ["critical", "high", "medium", "low"]) {
      expect(screen.getAllByText(level).length).toBeGreaterThan(0);
    }
  });

  it("reports which checks ran, passed, or did not apply", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(screen.getByText("Quality coverage")).toBeInTheDocument();
    expect(screen.getAllByText("Duplicate rows").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Passed").length).toBeGreaterThan(0);
    expect(screen.getByText("Not applicable")).toBeInTheDocument();
    expect(screen.getByText("Already clean")).toBeInTheDocument();
  });

  it("projects the health score from real penalties only", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(screen.getByText("Projected quality")).toBeInTheDocument();
    expect(screen.getByText(/recover 8 penalty points/)).toBeInTheDocument();
  });

  it("omits the projection when nothing is deterministically resolvable", () => {
    const noProjection: DatasetQualityResponse = {
      ...QUALITY,
      quality: {
        ...QUALITY.quality,
        projected_health_score: null,
        projected_health_band: null,
        resolvable_penalty: 0,
        resolvable_issue_types: [],
      },
    };
    render(<DatasetQualityPage data={noProjection} />);
    expect(screen.queryByText("Projected quality")).not.toBeInTheDocument();
  });

  it("exposes the deterministic scoring breakdown on request", async () => {
    const user = userEvent.setup();
    render(<DatasetQualityPage data={QUALITY} />);

    expect(screen.queryByText("Max penalty")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Show scoring breakdown/ }));
    expect(screen.getByText("Max penalty")).toBeInTheDocument();
    expect(screen.getByText("-2.94")).toBeInTheDocument();
  });

  it("says the file is never modified", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(
      screen.getByText(/Your uploaded file is never modified by this analysis/),
    ).toBeInTheDocument();
  });

  it("renders a clean dataset as a deliberate empty state", () => {
    const clean: DatasetQualityResponse = {
      ...QUALITY,
      quality: {
        ...QUALITY.quality,
        issues: [],
        health_score: 100,
        health_band: "excellent",
        missing_concentration: null,
        projected_health_score: null,
      },
      cleaning: [],
    };
    render(<DatasetQualityPage data={clean} />);
    expect(screen.getByText("No data quality issues were detected")).toBeInTheDocument();
    expect(screen.getByText("Nothing to clean")).toBeInTheDocument();
  });
});

describe("DatasetRelationshipsPage", () => {
  it("always carries the correlation disclaimer", () => {
    render(<DatasetRelationshipsPage data={RELATIONSHIPS} />);
    expect(
      screen.getByText(/does not show that one causes the other/),
    ).toBeInTheDocument();
  });

  it("shows the strongest correlation with its sample size", () => {
    render(<DatasetRelationshipsPage data={RELATIONSHIPS} />);
    expect(screen.getByText("age ↔ monthly_spend")).toBeInTheDocument();
    expect(screen.getByText(/0\.62/)).toBeInTheDocument();
    expect(screen.getByText(/n=1,180/)).toBeInTheDocument();
  });

  it("names excluded columns rather than silently omitting them", () => {
    render(<DatasetRelationshipsPage data={RELATIONSHIPS} />);
    expect(screen.getByText("customer_id")).toBeInTheDocument();
    expect(screen.getByText("Column is constant")).toBeInTheDocument();
  });

  it("shows an honest empty state when nothing can be correlated", () => {
    const none: DatasetRelationshipsResponse = {
      relationships: {
        ...RELATIONSHIPS.relationships,
        analyzable: false,
        unavailable_reason:
          "Correlation analysis needs at least two numeric columns with enough non-empty, varying values.",
        correlation_columns: [],
        correlation_matrix: [],
        strongest_positive: [],
        strongest_negative: [],
        group_differences: [],
        excluded_columns: [],
      },
      charts: [],
    };
    render(<DatasetRelationshipsPage data={none} />);
    expect(
      screen.getByText("No relationship analysis is possible for this dataset"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/needs at least two numeric columns/),
    ).toBeInTheDocument();
  });
});

describe("DatasetTrendsPage", () => {
  it("renders the timeline when a real date dimension exists", () => {
    render(<DatasetTrendsPage data={TRENDS_PRESENT} />);
    expect(screen.getByText("Timeline by created_at")).toBeInTheDocument();
    expect(screen.getByText("rising")).toBeInTheDocument();
    expect(screen.getByText("2024-03")).toBeInTheDocument();
  });

  it("states plainly that there is no temporal dimension, and fabricates none", () => {
    render(<DatasetTrendsPage data={TRENDS_ABSENT} />);
    expect(screen.getByText("No temporal analysis for this dataset")).toBeInTheDocument();
    expect(
      screen.getByText(/No reliable temporal dimension was detected in this dataset/),
    ).toBeInTheDocument();
    expect(screen.queryByText("rising")).not.toBeInTheDocument();
    expect(screen.queryByText(/Timeline by/)).not.toBeInTheDocument();
  });
});

describe("DatasetInsightsPage", () => {
  it("renders each insight with its evidence, impact and cited facts", () => {
    render(<DatasetInsightsPage data={INSIGHTS} />);
    expect(
      screen.getByText("Missing ages weaken every age-based statistic"),
    ).toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(
      screen.getByText(/Any average over this column silently excludes those rows/),
    ).toBeInTheDocument();
    // The cited fact is rendered as its measured statement, not an opaque id.
    expect(
      screen.getAllByText("177 of 1,203 rows have no value in 'customer_age'.").length,
    ).toBeGreaterThan(0);
  });

  it("explains why the findings are computed rather than synthesised", () => {
    render(<DatasetInsightsPage data={INSIGHTS} />);
    expect(
      screen.getByText("AI insight generation is disabled for this deployment."),
    ).toBeInTheDocument();
  });

  it("shows an empty state rather than inventing an insight", () => {
    render(<DatasetInsightsPage data={{ ...INSIGHTS, insights: [] }} />);
    expect(screen.getByText("No insights were produced")).toBeInTheDocument();
  });
});

describe("DatasetTextPanel", () => {
  it("reports per-column sentiment, themes and honest coverage", () => {
    render(<DatasetTextPanel report={TEXT_PRESENT} />);
    expect(screen.getByText("feedback")).toBeInTheDocument();
    // The coverage banner leads the card, so a sampled figure is met with
    // its denominator before any percentage.
    expect(
      screen.getByText(/Based on 500 of 1,203 text rows · 42% coverage/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/describe the analyzed sample, not the whole dataset/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Positive : Negative = 1\.50 : 1/)).toBeInTheDocument();
    expect(screen.getByText("dashboard · 100")).toBeInTheDocument();
    expect(screen.getByText("Representative positive")).toBeInTheDocument();
  });

  it("names the columns it deliberately did not analyze as text", () => {
    render(<DatasetTextPanel report={TEXT_PRESENT} />);
    expect(screen.getByText("Columns not analyzed as text")).toBeInTheDocument();
    expect(screen.getByText("customer_id")).toBeInTheDocument();
  });

  it("says there is no free-text column rather than showing empty sentiment", () => {
    render(<DatasetTextPanel report={TEXT_ABSENT} />);
    expect(screen.getByText("No text analysis for this dataset")).toBeInTheDocument();
    expect(screen.getByText(/deliberately excluded from text analysis/)).toBeInTheDocument();
  });
});

// ---- charts --------------------------------------------------------------

describe("DatasetChart", () => {
  const barSpec: DatasetChartSpec = {
    chart_id: "bar:country",
    kind: "bar",
    section: "explore",
    title: "Most common values in country",
    subtitle: "40 distinct values",
    x_label: "country",
    y_label: "Rows",
    columns: ["country"],
    data: [
      { label: "US", count: 500, percentage: 41.6 },
      { label: "Other", count: 200, percentage: 16.6 },
    ],
    coverage_note: "Showing the top 10 of 40 values; the remaining 30 are grouped as 'Other'.",
    meta: {},
  };

  it("renders the backend's own title, axes and coverage note", () => {
    render(<DatasetChart spec={barSpec} />);
    expect(screen.getByText("Most common values in country")).toBeInTheDocument();
    expect(screen.getByText("40 distinct values")).toBeInTheDocument();
    expect(screen.getByText("country · Rows")).toBeInTheDocument();
    expect(screen.getByText(/the remaining 30 are grouped as 'Other'/)).toBeInTheDocument();
  });

  it("renders an explicit empty state instead of a chart of nothing", () => {
    render(<DatasetChart spec={{ ...barSpec, data: [], coverage_note: null }} />);
    expect(
      screen.getByText("This chart has no data for the analyzed rows."),
    ).toBeInTheDocument();
  });

  it("renders a correlation heatmap cell for every pair, and a dash for an uncomputable one", () => {
    const heatmap: DatasetChartSpec = {
      chart_id: "relationships:heatmap",
      kind: "heatmap",
      section: "relationships",
      title: "Correlation between numeric columns",
      subtitle: "Pearson correlation. Correlation is not causation.",
      x_label: "Column",
      y_label: "Column",
      columns: ["a", "b"],
      data: [
        { row: "a", column: "a", value: 1 },
        { row: "a", column: "b", value: null },
        { row: "b", column: "a", value: null },
        { row: "b", column: "b", value: 1 },
      ],
      coverage_note: null,
      meta: {},
    };
    render(<DatasetChart spec={heatmap} />);
    const table = screen.getByRole("table");
    expect(within(table).getAllByText("1.00")).toHaveLength(2);
    // A pair with too few observations is blank, never drawn as 0.00 --
    // which would read as "no relationship" instead of "not computable".
    expect(within(table).getAllByText("–")).toHaveLength(2);
    expect(within(table).queryByText("0.00")).not.toBeInTheDocument();
  });

  it("renders the five-number summary for a box plot", () => {
    const box: DatasetChartSpec = {
      chart_id: "box:age",
      kind: "box_plot",
      section: "explore",
      title: "Spread and outliers in age",
      subtitle: "3 values outside [10, 90]",
      x_label: "age",
      y_label: "Value",
      columns: ["age"],
      data: [
        {
          minimum: 18,
          q1: 30,
          median: 42,
          q3: 55,
          maximum: 99,
          lower_bound: 10,
          upper_bound: 90,
          outlier_examples: [99],
        },
      ],
      coverage_note: null,
      meta: {},
    };
    render(<DatasetChart spec={box} />);
    expect(screen.getByText("Median")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("Outlier bounds")).toBeInTheDocument();
    expect(screen.getByText("10 to 90")).toBeInTheDocument();
  });
});


// ------------------------------- final refinement pass (Overview + Quality)

describe("Overview -- final refinement", () => {
  it("never contradicts the health badge with a stale band word in prose", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    expect(screen.getAllByText("Fair").length).toBeGreaterThan(0);
    expect(screen.getByText(/health score of 76\/100 \(Fair\)/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/76\/100 \(good\)/i);
  });

  it("renders the measured statements the summary is built from", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    for (const statement of OVERVIEW.executive_summary.strongest_findings) {
      expect(screen.getByText(statement)).toBeInTheDocument();
    }
  });

  it("keeps sampled text statements scoped to the sample", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    expect(
      screen.getByText(/Based on 300 of 1,203 text rows \(25% coverage, systematic sample\)/),
    ).toBeInTheDocument();
  });

  it("shows the missing-cell count against its denominator", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    expect(screen.getByText("Missing data in context")).toBeInTheDocument();
    expect(screen.getByText(/\/ 70,326 cells missing/)).toBeInTheDocument();
    expect(screen.getByText(/100% of it concentrated in 2 columns/)).toBeInTheDocument();
    expect(screen.getAllByText(/7,814 \/ 7,814 missing/).length).toBeGreaterThan(0);
  });

  it("says a structural gap is structural", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    expect(
      screen.getByText(/structural gap rather than scattered data loss/),
    ).toBeInTheDocument();
  });

  it("orders the page so the summary is read before the detail", () => {
    const { container } = render(<DatasetOverviewPage data={OVERVIEW} />);
    const headings = Array.from(container.querySelectorAll("h2")).map(
      (node) => node.textContent ?? "",
    );
    const order = [
      "Data health",
      "Executive summary",
      "What stands out",
      "Recommended actions",
      "Missing data in context",
      "Analysis coverage",
    ];
    const positions = order.map((title) => headings.indexOf(title));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });

  it("carries no unmeasured interpretation of sentiment", () => {
    render(<DatasetOverviewPage data={OVERVIEW} />);
    const text = document.body.textContent ?? "";
    for (const phrase of [
      "low engagement",
      "lack of engagement",
      "aspects of engagement",
      "disengaged",
      "weak interest",
    ]) {
      expect(text.toLowerCase()).not.toContain(phrase);
    }
  });

  it("omits the missingness section for a dataset with no concentration", () => {
    const clean: DatasetAnalysisResponse = {
      ...OVERVIEW,
      quality_summary: { ...OVERVIEW.quality_summary, missing_concentration: null },
    };
    render(<DatasetOverviewPage data={clean} />);
    expect(screen.queryByText("Missing data in context")).not.toBeInTheDocument();
  });
});

describe("Data Quality -- final refinement", () => {
  it("gives each detected issue its consequence, not just its measurement", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(screen.getAllByText(/Why it matters:/).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/This field currently provides no usable information/),
    ).toBeInTheDocument();
  });

  it("names the change rather than implying a control that does not exist", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(screen.getAllByText("Safe to remove").length).toBeGreaterThan(0);
    expect(screen.queryByText("Safe to apply")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /apply|preview fix|clean now/i }),
    ).not.toBeInTheDocument();
  });

  it("separates the decision, the diagnosis and the action", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(screen.getByText("What to fix first")).toBeInTheDocument();
    expect(screen.getAllByText(/^Decision:/).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText("All 1,203 rows are empty in 'legacy_code'."),
    ).toHaveLength(1);
    expect(screen.getByText(/^Why:/)).toBeInTheDocument();
    expect(
      screen.getByText(/nothing downstream can read anything from it/),
    ).toBeInTheDocument();
  });

  it("shows the projection as exact arithmetic over the published penalties", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(screen.getByText("Projected quality")).toBeInTheDocument();
    expect(screen.getByText("Current")).toBeInTheDocument();
    expect(screen.getByText("Projected")).toBeInTheDocument();
    expect(screen.getByText("90/100")).toBeInTheDocument();
    expect(
      screen.getByText(/assumes only the deterministically resolvable issues are fixed/),
    ).toBeInTheDocument();
    expect(screen.getByText(/recover 8 penalty points/)).toBeInTheDocument();
  });

  it("omits the projection entirely when nothing is safely recoverable", () => {
    const unrecoverable: DatasetQualityResponse = {
      ...QUALITY,
      quality: {
        ...QUALITY.quality,
        projected_health_score: null,
        projected_health_band: null,
        resolvable_penalty: 0,
        resolvable_issue_types: [],
      },
    };
    render(<DatasetQualityPage data={unrecoverable} />);
    expect(screen.queryByText("Projected quality")).not.toBeInTheDocument();
  });

  it("states passed checks compactly, with what they covered", () => {
    render(<DatasetQualityPage data={QUALITY} />);
    expect(screen.getByText("Already clean")).toBeInTheDocument();
    expect(screen.getAllByText("Duplicate rows").length).toBeGreaterThan(0);
    expect(screen.getAllByText("— Passed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("— 100% checked").length).toBeGreaterThan(0);
    expect(screen.getByText("Not applicable")).toBeInTheDocument();
  });

  it("orders the page from verdict to evidence to action", () => {
    const { container } = render(<DatasetQualityPage data={QUALITY} />);
    const headings = Array.from(container.querySelectorAll("h2")).map(
      (node) => node.textContent ?? "",
    );
    const order = [
      "Dataset health score",
      "Key quality insight",
      "What to fix first",
      "Where the problems are",
      "Detected issues",
      "Projected quality",
      "Quality coverage",
      "Cleaning recommendations",
    ];
    const positions = order.map((title) => headings.indexOf(title));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });
});
