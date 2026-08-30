"use client";

/**
 * The six dataset pages, rendered from persisted analysis sections.
 *
 * Nothing here computes a statistic, re-parses a file, or asks for a
 * generation -- every number on screen was measured by the engine during
 * the job and is being read back. That is why moving between these pages is
 * instant and why they all render with the AI provider offline.
 *
 * THE HONESTY RULES, which are the reason several of these components look
 * more verbose than they need to:
 *
 *   * A section with nothing behind it renders its own stated reason, taken
 *     from the backend, never a blank panel and never a fabricated
 *     substitute. "No reliable temporal dimension was detected" is the
 *     Trends page's real answer for a dataset with no dates.
 *   * Every coverage caveat the backend attached is rendered. A sampled
 *     analysis says so, a capped chart says so, a capped correlation matrix
 *     says so.
 *   * Correlation carries its disclaimer wherever it appears.
 *   * Semantic roles are shown with the evidence that produced them, so a
 *     detected role is auditable rather than asserted.
 */

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Database,
  FileSpreadsheet,
  Gauge,
  Info,
  ListChecks,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Waypoints,
  Wrench,
} from "lucide-react";
import type { ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { CARD_GLOW_ACCENT, CARD_GLOW_CLASS, CARD_GLOW_SUBTLE } from "@/lib/card-glow";
import { healthBadgeClass, healthBandLabel, healthToneClass } from "@/lib/dataset-health";
import { cn } from "@/lib/utils";
import { DatasetChart, DatasetChartGrid } from "./dataset-charts";
import type {
  DatasetAnalysisResponse,
  DatasetCleaningRecommendation,
  DatasetColumnProfile,
  DatasetCoverageArea,
  DatasetCoverageStatus,
  DatasetInsight,
  DatasetInsightsResponse,
  DatasetMissingConcentration,
  DatasetQualityIssue,
  DatasetQualityResponse,
  DatasetQualitySeverity,
  DatasetRelationshipsResponse,
  DatasetSemanticRole,
  DatasetTextReport,
  DatasetTrendsResponse,
} from "@/lib/api/dataset-analysis";

// ---------------------------------------------------------------- tokens

const SEVERITY_STYLE: Record<DatasetQualitySeverity, string> = {
  critical: "border-red-400/35 bg-red-500/15 text-red-200",
  high: "border-rose-400/30 bg-rose-500/10 text-rose-200",
  medium: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  low: "border-slate-400/25 bg-slate-500/10 text-slate-300",
};

const ROLE_LABEL: Record<DatasetSemanticRole, string> = {
  identifier: "Identifier",
  numeric_metric: "Numeric metric",
  currency: "Monetary value",
  percentage: "Percentage",
  categorical_dimension: "Category",
  datetime_dimension: "Date",
  free_text: "Free text",
  email: "Email",
  url: "URL",
  geographic: "Location",
  boolean_flag: "Flag",
  unknown: "Generic",
};

const CHIP_BASE =
  "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold";
const NEUTRAL_CHIP = "border-white/10 bg-white/[0.04] text-slate-300";

function Chip({ className, children }: { className?: string; children: ReactNode }) {
  return <span className={cn(CHIP_BASE, className)}>{children}</span>;
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  if (Number.isInteger(value)) return value.toLocaleString();
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "--";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ------------------------------------------------------ shared surfaces

function PageSurface({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-5">{children}</div>;
}

function SectionCard({
  title,
  description,
  icon: Icon,
  accent = false,
  children,
}: {
  title: string;
  description?: string;
  icon?: React.ComponentType<{ className?: string }>;
  accent?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={cn(accent ? CARD_GLOW_ACCENT : CARD_GLOW_CLASS, "flex flex-col gap-4 p-5")}>
      <header className="flex items-start gap-3">
        {Icon ? (
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/10">
            <Icon className="h-4 w-4 text-violet-200" />
          </span>
        ) : null}
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          {description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          ) : null}
        </div>
      </header>
      {children}
    </section>
  );
}

/** The one honest-empty-state component.
 *
 * Takes the backend's own reason rather than composing a generic sentence,
 * because the backend is the only thing that knows WHY a section has
 * nothing -- no date column, too few rows, one period, no free-text column,
 * a text pipeline that was unavailable. Each needs a different next step. */
export function DatasetEmptyState({ title, reason }: { title: string; reason: string | null }) {
  return (
    <div
      className={cn(
        CARD_GLOW_SUBTLE,
        "flex flex-col items-start gap-1.5 border-white/10 px-4 py-6 text-start",
      )}
    >
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
        <Info className="h-4 w-4 shrink-0 text-slate-400" />
        {title}
      </div>
      {reason ? <p className="text-xs leading-5 text-muted-foreground">{reason}</p> : null}
    </div>
  );
}

function CoverageNotice({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null;
  return (
    <div
      className={cn(
        CARD_GLOW_SUBTLE,
        "flex flex-col gap-1 border-amber-400/20 bg-amber-500/[0.04] px-4 py-3",
      )}
    >
      <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-200">
        Coverage notes
      </span>
      {notes.map((note, index) => (
        <p key={index} className="text-xs leading-5 text-amber-100/85">
          {note}
        </p>
      ))}
    </div>
  );
}

function MetricTile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className={cn(CARD_GLOW_SUBTLE, "flex flex-col gap-1 p-4")}>
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className={cn("text-xl font-semibold text-foreground", tone)}>{value}</span>
      {hint ? <span className="text-[11px] text-muted-foreground">{hint}</span> : null}
    </div>
  );
}

function SummaryList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone?: "risk";
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </span>
      <ul className="flex flex-col gap-1.5">
        {items.map((item, index) => (
          <li key={index} className="flex items-start gap-2 text-xs leading-5">
            {tone === "risk" ? (
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />
            ) : (
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-violet-300" />
            )}
            <span className="text-slate-200">{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ------------------------------------------------- coverage + concentration
//
// Shared by Overview and Data Quality, because both answer the same
// question from different sides: what was actually analyzed, and where the
// missing cells actually are.

const COVERAGE_STATUS_LABEL: Record<DatasetCoverageStatus, string> = {
  full: "Full",
  sampled: "Sampled",
  not_applicable: "Not applicable",
  unavailable: "Unavailable",
};

const COVERAGE_STATUS_STYLE: Record<DatasetCoverageStatus, string> = {
  full: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
  sampled: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  not_applicable: "border-slate-400/25 bg-slate-500/10 text-slate-400",
  unavailable: "border-rose-400/30 bg-rose-500/10 text-rose-200",
};

/** Per-area coverage.
 *
 * The single headline percentage describes row profiling only. Text
 * analysis is capped separately and is routinely a fraction of it, and
 * showing one number for the whole analysis is what let a 25%-sampled
 * sentiment result sit under a "100% analyzed" banner. */
function AnalysisCoverage({ areas }: { areas: DatasetCoverageArea[] }) {
  if (areas.length === 0) return null;
  return (
    <SectionCard
      title="Analysis coverage"
      description="What each part of the analysis actually ran over. A sampled area describes its sample, not the whole dataset."
      icon={Gauge}
    >
      <ul className="flex flex-col gap-1.5">
        {areas.map((area) => (
          <li
            key={area.area}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2"
          >
            <div className="flex min-w-0 flex-col">
              <span className="text-xs font-medium text-foreground">{area.label}</span>
              {area.detail ? (
                <span className="truncate text-[11px] text-muted-foreground">{area.detail}</span>
              ) : null}
              {area.status === "sampled" && area.analyzed !== null && area.total !== null ? (
                <span className="text-[11px] font-medium text-amber-200/90">
                  {formatNumber(area.analyzed)} of {formatNumber(area.total)} rows analyzed
                  {area.coverage_percentage !== null
                    ? ` · ${area.coverage_percentage.toFixed(0)}% coverage`
                    : ""}{" "}
                  · systematic sample. Every figure from this area describes the sample.
                </span>
              ) : null}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {area.coverage_percentage !== null ? (
                <span className="text-xs font-semibold tabular-nums text-foreground">
                  {area.coverage_percentage.toFixed(0)}%
                </span>
              ) : null}
              <Chip className={COVERAGE_STATUS_STYLE[area.status]}>
                {COVERAGE_STATUS_LABEL[area.status]}
              </Chip>
            </div>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

/** Turns "22.2% of cells are empty" into a fact somebody can act on.
 *
 * The headline percentage alone reads as a dataset riddled with gaps. It is
 * a completely different situation when every one of those cells belongs to
 * columns that are empty from top to bottom and every populated column is
 * complete -- so the page says which of the two it is. */
export function MissingConcentrationNote({
  concentration,
  missingPercentage,
  totalCells,
}: {
  concentration: DatasetMissingConcentration | null;
  missingPercentage: number;
  totalCells?: number;
}) {
  if (!concentration || !concentration.concentrated) return null;

  const allFromEmpty = concentration.empty_column_share_percentage >= 99.5;
  const emptyCount = concentration.empty_columns.length;
  const share = allFromEmpty
    ? concentration.empty_column_share_percentage
    : concentration.top_share_percentage;

  return (
    <div className={cn(CARD_GLOW_SUBTLE, "flex flex-col gap-2.5 border-white/10 p-4")}>
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Info className="h-4 w-4 shrink-0 text-violet-300" />
        {allFromEmpty && emptyCount > 0
          ? `All missing data comes from ${emptyCount} completely empty column${emptyCount === 1 ? "" : "s"}`
          : `Missing data is concentrated in ${concentration.top_columns.length} column${concentration.top_columns.length === 1 ? "" : "s"}`}
      </div>

      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-lg font-semibold tabular-nums text-foreground">
          {formatNumber(concentration.missing_cells)}
          {typeof totalCells === "number" && totalCells > 0 ? (
            <span className="text-sm font-normal text-muted-foreground">
              {" "}
              / {formatNumber(totalCells)} cells missing
            </span>
          ) : (
            <span className="text-sm font-normal text-muted-foreground"> cells missing</span>
          )}
        </span>
        <span className="text-xs text-muted-foreground">
          {missingPercentage.toFixed(1)}% of the dataset · {share.toFixed(0)}% of it concentrated
          in {allFromEmpty ? emptyCount : concentration.top_columns.length} column
          {(allFromEmpty ? emptyCount : concentration.top_columns.length) === 1 ? "" : "s"}
        </span>
      </div>

      <p className="text-xs leading-5 text-slate-300">
        {allFromEmpty && emptyCount > 0 ? (
          <>
            Every missing cell belongs to{" "}
            {concentration.empty_columns.map((name) => `"${name}"`).join(" and ")}, which
            {emptyCount === 1 ? " is" : " are"} empty from top to bottom.
            {concentration.populated_columns_complete
              ? " Every remaining column is fully populated, so this is a structural gap rather than scattered data loss — row-level completeness is unaffected."
              : null}
          </>
        ) : (
          <>
            {concentration.top_share_percentage.toFixed(1)}% of the{" "}
            {formatNumber(concentration.missing_cells)} missing cells sit in{" "}
            {concentration.top_columns.length} of {concentration.columns_with_missing} affected
            columns, so the gap is a property of those columns rather than of the dataset as a
            whole.
          </>
        )}
      </p>
      <ul className="flex flex-col gap-1">
        {concentration.top_columns.map((entry) => (
          <li key={entry.column} className="flex items-center justify-between gap-3 text-[11px]">
            <span className="min-w-0 truncate font-medium text-slate-300">{entry.column}</span>
            <span className="shrink-0 tabular-nums text-muted-foreground">
              {formatNumber(entry.missing_count)}
              {typeof entry.analyzed_rows === "number"
                ? ` / ${formatNumber(entry.analyzed_rows)}`
                : ""}{" "}
              missing · {entry.missing_percentage_of_column.toFixed(0)}% of column ·{" "}
              {entry.share_of_missing.toFixed(0)}% of all gaps
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Current against projected, when the projection is exact.
 *
 * Only rendered when the backend computed one from real penalties -- see
 * QualityReport.projected_health_score. Nothing here estimates. */
function ProjectedHealth({
  current,
  projected,
}: {
  current: number;
  projected: number | null;
}) {
  if (projected === null || projected <= current) return null;
  return (
    <div className="flex items-center gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
        After recommended fixes
      </span>
      <span className="flex items-center gap-2 text-sm font-semibold">
        <span className={healthToneClass(current)}>{current}</span>
        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
        <span className={healthToneClass(projected)}>{projected}</span>
        <span className="text-[11px] font-normal text-muted-foreground">
          {healthBandLabel(projected)}
        </span>
      </span>
    </div>
  );
}

// ------------------------------------------------------------- Overview

/** Friendly names for semantic roles, grouped so the Overview can say what
 * the columns MEAN rather than what shape they are.
 *
 * The distinction is the point: a summary reading "5 × text" made five
 * columns look like five free-text NLP fields when in fact one was, two were
 * identifiers and two were unclassified. */
const ROLE_GROUP: Record<DatasetSemanticRole, string> = {
  free_text: "free text",
  datetime_dimension: "datetime",
  categorical_dimension: "categorical",
  geographic: "location",
  numeric_metric: "numeric metric",
  currency: "monetary",
  percentage: "percentage",
  boolean_flag: "flag",
  identifier: "identifier",
  email: "email",
  url: "URL",
  unknown: "unclassified",
};

/** Semantic composition, ordered so the analytically interesting roles come
 * first and identifiers/unclassified columns fall to the end. */
function semanticComposition(
  roles: Record<string, number>,
): { label: string; count: number }[] {
  const order: DatasetSemanticRole[] = [
    "free_text",
    "datetime_dimension",
    "categorical_dimension",
    "geographic",
    "numeric_metric",
    "currency",
    "percentage",
    "boolean_flag",
    "identifier",
    "email",
    "url",
    "unknown",
  ];
  return order
    .filter((role) => (roles[role] ?? 0) > 0)
    .map((role) => ({ label: ROLE_GROUP[role], count: roles[role]! }));
}

export function DatasetOverviewPage({ data }: { data: DatasetAnalysisResponse }) {
  const { overview, coverage, quality_summary: quality, executive_summary: summary } = data;
  const bandLabel = healthBandLabel(quality.health_score);
  const bandTone = healthToneClass(quality.health_score);
  const emptyColumnCount = overview.type_breakdown["empty"] ?? 0;

  return (
    <PageSurface>
      {/* 1. Dataset identity and scope */}
      <SectionCard
        title={overview.file_name}
        description={`${overview.file_type.toUpperCase()} · ${formatBytes(
          overview.file_size_bytes,
        )}${overview.sheet_name ? ` · sheet "${overview.sheet_name}"` : ""}`}
        icon={FileSpreadsheet}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricTile label="Rows" value={formatNumber(overview.row_count)} />
          <MetricTile label="Columns" value={formatNumber(overview.column_count)} />
          <MetricTile
            label="Health score"
            value={`${quality.health_score}/100`}
            hint={bandLabel}
            tone={bandTone}
          />
          <MetricTile
            label="Missing cells"
            value={`${overview.missing_percentage.toFixed(1)}%`}
            hint={`${formatNumber(overview.missing_cells)} of ${formatNumber(
              overview.total_cells,
            )} cells`}
          />
        </div>

        {/* Semantic composition -- what the columns MEAN. */}
        <div className="flex flex-col gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Column roles
          </span>
          <div className="flex flex-wrap gap-1.5">
            {semanticComposition(overview.role_breakdown).map((entry) => (
              <Chip key={entry.label} className={NEUTRAL_CHIP}>
                {entry.count} {entry.label}
              </Chip>
            ))}
            {emptyColumnCount > 0 ? (
              <Chip className={SEVERITY_STYLE.high}>{emptyColumnCount} empty</Chip>
            ) : null}
          </div>
          <span className="text-[11px] leading-5 text-muted-foreground">
            Roles are what a column means. Storage types (
            {Object.entries(overview.type_breakdown)
              .map(([type, count]) => `${count} ${type}`)
              .join(", ")}
            ) describe how the values are stored, which is a different question.
          </span>
        </div>

        {overview.warnings.length > 0 ? (
          <div className="flex flex-col gap-1">
            {overview.warnings.map((warning, index) => (
              <p key={index} className="text-xs text-amber-200/85">
                {warning}
              </p>
            ))}
          </div>
        ) : null}
      </SectionCard>

      {/* 2. Health */}
      <SectionCard
        title="Data health"
        description="Deterministic: the score starts at 100 and each detected issue subtracts a documented penalty. No model is involved."
        icon={CheckCircle2}
      >
        <div className="flex flex-wrap items-center gap-3">
          <span className={cn("text-2xl font-semibold", bandTone)}>
            {quality.health_score}
            <span className="text-sm font-normal text-muted-foreground">/100</span>
          </span>
          <Chip className={healthBadgeClass(quality.health_score)}>{bandLabel}</Chip>
          <Chip className={NEUTRAL_CHIP}>
            {quality.issue_count} issue{quality.issue_count === 1 ? "" : "s"}
          </Chip>
          {quality.duplicate_rows > 0 ? (
            <Chip className={NEUTRAL_CHIP}>
              {formatNumber(quality.duplicate_rows)} duplicate rows
            </Chip>
          ) : null}
        </div>

        <ProjectedHealth
          current={quality.health_score}
          projected={quality.projected_health_score}
        />
      </SectionCard>

      {/* 3. Executive summary */}
      <SectionCard
        title="Executive summary"
        description={
          summary.generated_by === "ai"
            ? "Framed by the AI stage; every statement below is a measured fact."
            : "Computed directly from the measured analysis."
        }
        icon={Database}
        accent
      >
        <div className="flex flex-col gap-2 text-sm">
          <p className="text-foreground">{summary.scope}</p>
          <p className="text-muted-foreground">{summary.data_health}</p>
        </div>
        {summary.strongest_findings.length > 0 ? (
          <ol className="flex flex-col gap-2 border-t border-white/[0.06] pt-3">
            {summary.strongest_findings.map((statement, index) => (
              <li key={index} className="flex items-start gap-2.5 text-xs leading-5">
                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/[0.04] text-[9px] font-semibold text-slate-300 tabular-nums">
                  {index + 1}
                </span>
                <span className="text-slate-200">{statement}</span>
              </li>
            ))}
          </ol>
        ) : null}
        {summary.key_risks.length > 0 ? (
          <SummaryList title="Most important risk" items={summary.key_risks.slice(0, 2)} tone="risk" />
        ) : null}
      </SectionCard>

      {/* 4. What stands out */}
      {data.strongest_findings.length > 0 ? (
        <SectionCard
          title="What stands out"
          description="The highest-value findings, each backed by a measured fact."
          icon={Sparkles}
        >
          <div className="flex flex-col gap-3">
            {data.strongest_findings.map((insight, index) => (
              <InsightCard key={index} insight={insight} compact />
            ))}
          </div>
        </SectionCard>
      ) : null}

      {/* 5. Recommended actions */}
      {summary.recommended_actions.length > 0 ? (
        <SectionCard
          title="Recommended actions"
          description="Each one names what to inspect, why, and what the answer decides."
          icon={Wrench}
        >
          <ol className="flex flex-col gap-2">
            {summary.recommended_actions.map((action, index) => (
              <li key={index} className="flex items-start gap-2.5 text-xs leading-5">
                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-primary/30 bg-primary/10 text-[9px] font-semibold text-violet-200">
                  {index + 1}
                </span>
                <span className="text-slate-200">{action}</span>
              </li>
            ))}
          </ol>
        </SectionCard>
      ) : null}

      {/* 6. Missing data in context */}
      {quality.missing_concentration?.concentrated ? (
        <SectionCard
          title="Missing data in context"
          description="Where the gaps actually are, before the headline percentage is read as scattered data loss."
          icon={Info}
        >
          <MissingConcentrationNote
            concentration={quality.missing_concentration}
            missingPercentage={overview.missing_percentage}
            totalCells={overview.total_cells}
          />
        </SectionCard>
      ) : null}

      {/* 7. Analysis coverage -- including the sampled NLP scope. */}
      <AnalysisCoverage areas={coverage.areas} />
      <CoverageNotice notes={coverage.notes} />

      {/* 8. Compact visual summary */}
      {data.charts.length > 0 ? (
        <SectionCard title="At a glance" icon={AlertTriangle}>
          <DatasetChartGrid charts={data.charts} />
        </SectionCard>
      ) : null}
    </PageSurface>
  );
}

// --------------------------------------------------------- Data Quality

const CHECK_STATUS_STYLE: Record<string, string> = {
  passed: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
  issues_found: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  not_applicable: "border-slate-400/25 bg-slate-500/10 text-slate-400",
};

/** Names the change, since nothing in the product actually applies it. */
const SAFE_ACTION_LABEL: Record<string, string> = {
  drop_column: "Safe to remove",
  remove_duplicate_rows: "Safe to de-duplicate",
  normalize_category_casing: "Safe to standardise",
  trim_whitespace: "Safe to trim",
};

const APPLICABILITY_LABEL: Record<string, string> = {
  safe: "Low risk",
  review: "Needs a decision",
  manual: "Manual review",
};

function applicabilityLabel(applicability: string, action?: string): string {
  if (applicability === "safe" && action && SAFE_ACTION_LABEL[action]) {
    return SAFE_ACTION_LABEL[action];
  }
  return APPLICABILITY_LABEL[applicability] ?? applicability;
}

/** Consequence per issue type -- a property of the type, not of any file. */
const WHY_IT_MATTERS: Record<string, string> = {
  empty_column: "This field currently provides no usable information to any analysis.",
  constant_column:
    "A column with one repeated value cannot distinguish between rows, so it cannot explain anything.",
  missing_values:
    "Every statistic on this column is computed over a smaller population than the row count implies.",
  duplicate_rows: "Counts, sums and averages over the dataset are all overstated.",
  duplicate_identifier:
    "The column cannot be trusted as a key, so joins and de-duplication on it are unsafe.",
  inconsistent_types:
    "Mixed value types keep the column out of numeric and date statistics entirely.",
  malformed_numeric: "These rows are silently excluded from every numeric statistic.",
  malformed_dates: "These rows are silently excluded from every trend and time bucket.",
  inconsistent_casing: "One real category is being counted as several.",
  whitespace_only: "These cells read as populated but hold nothing.",
  numeric_outliers:
    "The mean and the standard deviation are pulled by these rows; the median is not.",
  high_cardinality: "The column cannot group anything, so charts and segments on it are unusable.",
  suspicious_values:
    "The values do not match what the column name describes, so figures from it may measure something else.",
};

const APPLICABILITY_STYLE: Record<string, string> = {
  safe: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
  review: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  manual: "border-slate-400/25 bg-slate-500/10 text-slate-300",
};

/** The 1-3 things worth doing first, ranked by the score they recover.
 *
 * Ranked by real penalty rather than by severity label, because the penalty
 * is what the health score is actually made of -- so "fix this first" and
 * "this costs the most" cannot disagree. */
function WhatToFixFirst({
  issues,
  cleaning,
}: {
  issues: DatasetQualityIssue[];
  cleaning: DatasetCleaningRecommendation[];
}) {
  const ranked = [...issues].sort((a, b) => b.score_penalty - a.score_penalty).slice(0, 3);
  if (ranked.length === 0) return null;

  return (
    <SectionCard
      title="What to fix first"
      description="The decision queue: what to deal with, in what order, and how much score each one returns."
      icon={ListChecks}
    >
      <ol className="flex flex-col gap-2.5">
        {ranked.map((issue, index) => {
          const action = cleaning.find(
            (item) => item.source_issue === issue.issue_type && item.column === issue.column,
          );
          return (
            <li
              key={`${issue.issue_type}-${issue.column ?? "dataset"}`}
              className="flex items-start gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] p-3"
            >
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-primary/30 bg-primary/10 text-[10px] font-semibold text-violet-200">
                {index + 1}
              </span>
              <div className="flex min-w-0 flex-col gap-1.5">
                <span className="text-sm font-semibold text-foreground">
                  {issue.column ?? "Whole dataset"}
                </span>
                <span className="text-[11px] leading-5 tabular-nums text-muted-foreground">
                  {formatNumber(issue.affected_count)} affected ·{" "}
                  {issue.affected_percentage.toFixed(1)}%
                </span>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Chip className={SEVERITY_STYLE[issue.severity]}>{issue.severity}</Chip>
                  <Chip className={NEUTRAL_CHIP}>recovers {issue.score_penalty} points</Chip>
                  {action ? (
                    <Chip className={APPLICABILITY_STYLE[action.applicability] ?? NEUTRAL_CHIP}>
                      {applicabilityLabel(action.applicability, action.action)}
                    </Chip>
                  ) : null}
                </div>
                <span className="text-[11px] leading-5 text-slate-300">
                  <span className="font-medium text-slate-200">Decision: </span>
                  {action?.title ?? issue.title}
                  {action?.applicability === "safe"
                    ? " — no information would be lost, but confirm the source or export was not expected to populate it."
                    : action?.applicability === "review"
                      ? " — the right choice depends on what the column is used for downstream."
                      : ""}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
    </SectionCard>
  );
}

/** Missing values with the numbers written out.
 *
 * A bar whose length the reader has to translate back into a count is a
 * worse table than a table. */
function MissingByColumn({ columns }: { columns: DatasetMissingConcentration["top_columns"] }) {
  if (columns.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      {columns.map((entry) => (
        <div
          key={entry.column}
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2"
        >
          <span className="min-w-0 truncate text-xs font-medium text-foreground">
            {entry.column}
          </span>
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {formatNumber(entry.missing_count)}
            {typeof entry.analyzed_rows === "number"
              ? ` / ${formatNumber(entry.analyzed_rows)}`
              : ""}{" "}
            missing ·{" "}
            <span
              className={
                entry.missing_percentage_of_column >= 100
                  ? "text-rose-200"
                  : "text-muted-foreground"
              }
            >
              {entry.missing_percentage_of_column.toFixed(0)}%
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}

/** Severity counts. A chart for a single non-zero bar is decoration; a
 * four-number row says the same thing in a fifth of the space. */
function SeveritySummary({ counts }: { counts: Record<string, number> }) {
  const levels: DatasetQualitySeverity[] = ["critical", "high", "medium", "low"];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {levels.map((level) => (
        <div
          key={level}
          className={cn(
            "flex items-center justify-between rounded-lg border px-3 py-2",
            (counts[level] ?? 0) > 0
              ? SEVERITY_STYLE[level]
              : "border-white/[0.06] bg-white/[0.02] text-muted-foreground",
          )}
        >
          <span className="text-[11px] font-medium capitalize">{level}</span>
          <span className="text-sm font-semibold tabular-nums">{counts[level] ?? 0}</span>
        </div>
      ))}
    </div>
  );
}

export function DatasetQualityPage({ data }: { data: DatasetQualityResponse }) {
  const { quality, cleaning, charts } = data;
  const bandLabel = healthBandLabel(quality.health_score);
  const bandTone = healthToneClass(quality.health_score);
  const [showRules, setShowRules] = useState(false);

  const severityCount = (["critical", "high", "medium", "low"] as const).filter(
    (level) => (quality.counts_by_severity[level] ?? 0) > 0,
  ).length;
  // A severity chart earns its space only when there is more than one level
  // to compare.
  const severityCharts = severityCount > 1 ? charts.filter((c) => c.chart_id === "quality:severity") : [];
  const missingChart = charts.find((c) => c.chart_id === "quality:missing");
  const concentration = quality.missing_concentration;
  const passed = quality.checks.filter((check) => check.status === "passed");

  return (
    <PageSurface>
      {/* 1. Health summary */}
      <SectionCard
        title="Dataset health score"
        description="Deterministic and fully explained: the score starts at 100 and each detected issue subtracts a penalty scaled by how much of the dataset it affects. No model is involved."
        icon={CheckCircle2}
      >
        <div className="flex flex-wrap items-center gap-3">
          <span className={cn("text-2xl font-semibold", bandTone)}>
            {quality.health_score}
            <span className="text-sm font-normal text-muted-foreground">/100</span>
          </span>
          <Chip className={healthBadgeClass(quality.health_score)}>{bandLabel}</Chip>
        </div>

        <SeveritySummary counts={quality.counts_by_severity} />

        <div className="grid gap-3 sm:grid-cols-3">
          <MetricTile
            label="Missing cells"
            value={`${quality.missing_percentage.toFixed(1)}%`}
            hint={`${formatNumber(quality.missing_cells)} of ${formatNumber(quality.total_cells)}`}
          />
          <MetricTile
            label="Duplicate rows"
            value={formatNumber(quality.duplicate_rows)}
            hint={`${quality.duplicate_row_percentage.toFixed(1)}% of rows`}
          />
          <MetricTile label="Issues found" value={formatNumber(quality.issues.length)} />
        </div>

        <div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-[11px]"
            onClick={() => setShowRules((open) => !open)}
          >
            {showRules ? "Hide scoring breakdown" : "Show scoring breakdown"}
          </Button>
          {showRules ? (
            <div className={cn(CARD_GLOW_SUBTLE, "mt-2 overflow-x-auto p-3")}>
              <table className="w-full min-w-[380px] text-[11px]">
                <thead>
                  <tr className="text-muted-foreground">
                    <th className="p-1 text-start font-medium">Issue type</th>
                    <th className="p-1 text-end font-medium">Max penalty</th>
                    <th className="p-1 text-end font-medium">Applied</th>
                  </tr>
                </thead>
                <tbody>
                  {quality.scoring_rules.map((rule) => (
                    <tr key={rule.issue_type} className="border-t border-white/5">
                      <td className="p-1 text-slate-300">{rule.issue_type.replace(/_/g, " ")}</td>
                      <td className="p-1 text-end text-muted-foreground">{rule.max_penalty}</td>
                      <td
                        className={cn(
                          "p-1 text-end font-medium",
                          rule.applied > 0 ? "text-amber-200" : "text-muted-foreground",
                        )}
                      >
                        -{rule.applied}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </SectionCard>

      {/* 2. Key quality insight */}
      {concentration?.concentrated ? (
        <SectionCard
          title="Key quality insight"
          description="What the missing-cell percentage actually means for this dataset."
          icon={Info}
          accent
        >
          <MissingConcentrationNote
            concentration={concentration}
            missingPercentage={quality.missing_percentage}
            totalCells={quality.total_cells}
          />
        </SectionCard>
      ) : null}

      {/* 3. What to fix first */}
      <WhatToFixFirst issues={quality.issues} cleaning={cleaning} />

      {/* 4. Where the problems are */}
      {concentration && concentration.top_columns.length > 0 ? (
        <SectionCard
          title="Where the problems are"
          description="Missing values by column, with the counts written out."
          icon={AlertTriangle}
        >
          <MissingByColumn columns={concentration.top_columns} />
          {severityCharts.length > 0 ? <DatasetChartGrid charts={severityCharts} /> : null}
        </SectionCard>
      ) : missingChart ? (
        <SectionCard title="Where the problems are" icon={AlertTriangle}>
          <DatasetChartGrid charts={[missingChart, ...severityCharts]} />
        </SectionCard>
      ) : null}

      {/* 5. Detected issues -- the DIAGNOSIS and the audit trail. */}
      <SectionCard
        title="Detected issues"
        description="The evidence behind the score: what was flagged, how much it affects, what it costs, and why it matters."
        icon={AlertTriangle}
      >
        {quality.issues.length === 0 ? (
          <DatasetEmptyState
            title="No data quality issues were detected"
            reason="Every check this engine runs came back clean for this dataset."
          />
        ) : (
          <div className="flex flex-col gap-3">
            {quality.issues.map((issue, index) => (
              <article key={index} className={cn(CARD_GLOW_SUBTLE, "flex flex-col gap-2 p-4")}>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Chip className={SEVERITY_STYLE[issue.severity]}>{issue.severity}</Chip>
                  {issue.column ? <Chip className={NEUTRAL_CHIP}>{issue.column}</Chip> : null}
                  <Chip className={NEUTRAL_CHIP}>
                    {formatNumber(issue.affected_count)} affected ·{" "}
                    {issue.affected_percentage.toFixed(1)}%
                  </Chip>
                  <Chip className={NEUTRAL_CHIP}>-{issue.score_penalty} score</Chip>
                </div>
                <h3 className="text-sm font-semibold text-foreground">{issue.title}</h3>
                <p className="text-xs leading-5 text-slate-300">{issue.explanation}</p>
                {WHY_IT_MATTERS[issue.issue_type] ? (
                  <p className="text-xs leading-5 text-muted-foreground">
                    <span className="font-medium text-slate-300">Why it matters: </span>
                    {WHY_IT_MATTERS[issue.issue_type]}
                  </p>
                ) : null}
                {issue.examples.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {issue.examples.map((example, exampleIndex) => (
                      <code
                        key={exampleIndex}
                        className="rounded bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-slate-300"
                      >
                        {example}
                      </code>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </SectionCard>

      {/* 6. Projected quality */}
      {quality.projected_health_score !== null &&
      quality.projected_health_score > quality.health_score ? (
        <SectionCard
          title="Projected quality"
          description="Exact arithmetic over the published penalties -- not an estimate, and not model-produced."
          icon={TrendingUp}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <MetricTile
              label="Current"
              value={`${quality.health_score}/100`}
              hint={bandLabel}
              tone={bandTone}
            />
            <MetricTile
              label="Projected"
              value={`${quality.projected_health_score}/100`}
              hint={healthBandLabel(quality.projected_health_score)}
              tone={healthToneClass(quality.projected_health_score)}
            />
          </div>
          <p className="text-[11px] leading-5 text-muted-foreground">
            The projection assumes only the deterministically resolvable issues are fixed (
            {quality.resolvable_issue_types.map((type) => type.replace(/_/g, " ")).join(", ")}),
            which would recover {quality.resolvable_penalty} penalty points. Issues that need a
            human decision -- how to fill missing values, whether an outlier is real -- are
            excluded, because their effect depends on the decision taken.
          </p>
        </SectionCard>
      ) : null}

      {/* 7. Quality coverage and passed checks */}
      {quality.checks.length > 0 ? (
        <SectionCard
          title="Quality coverage"
          description="Which checks ran, over how much of the data, and what they found."
          icon={ShieldCheck}
        >
          <ul className="flex flex-col gap-1.5">
            {quality.checks.map((check) => (
              <li
                key={check.check}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2"
              >
                <div className="flex min-w-0 flex-col">
                  <span className="text-xs font-medium text-foreground">{check.label}</span>
                  {check.detail ? (
                    <span className="truncate text-[11px] text-muted-foreground">
                      {check.detail}
                    </span>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {check.coverage !== "none" ? (
                    <span className="text-[11px] text-muted-foreground">
                      {check.coverage === "sampled" ? "Sampled" : "Full — 100%"}
                    </span>
                  ) : null}
                  <Chip className={CHECK_STATUS_STYLE[check.status] ?? NEUTRAL_CHIP}>
                    {check.status === "issues_found"
                      ? "Issues found"
                      : check.status === "not_applicable"
                        ? "Not applicable"
                        : "Passed"}
                  </Chip>
                </div>
              </li>
            ))}
          </ul>

          {passed.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Already clean
              </span>
              <ul className="flex flex-col gap-1">
                {passed.map((check) => (
                  <li
                    key={check.check}
                    className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px]"
                  >
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-300" />
                    <span className="font-medium text-slate-200">{check.label}</span>
                    <span className="text-muted-foreground">— Passed</span>
                    <span className="text-muted-foreground">
                      — {check.coverage === "sampled" ? "sampled" : "100%"} checked
                    </span>
                    {check.detail ? (
                      <span className="text-muted-foreground">· {check.detail}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </SectionCard>
      ) : null}

      {/* 8. Cleaning recommendations */}
      <SectionCard
        title="Cleaning recommendations"
        description="Descriptions only. Your uploaded file is never modified by this analysis, and nothing here is executed."
        icon={Wrench}
      >
        {cleaning.length === 0 ? (
          <DatasetEmptyState
            title="Nothing to clean"
            reason="No detected issue in this dataset has a remediation worth recommending."
          />
        ) : (
          <div className="flex flex-col gap-3">
            {cleaning.map((recommendation, index) => (
              <article key={index} className={cn(CARD_GLOW_SUBTLE, "flex flex-col gap-2 p-4")}>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Chip className={APPLICABILITY_STYLE[recommendation.applicability] ?? NEUTRAL_CHIP}>
                    {applicabilityLabel(recommendation.applicability, recommendation.action)}
                  </Chip>
                  {recommendation.column ? (
                    <Chip className={NEUTRAL_CHIP}>{recommendation.column}</Chip>
                  ) : null}
                  <Chip className={NEUTRAL_CHIP}>{recommendation.affected_data}</Chip>
                </div>
                <h3 className="text-sm font-semibold text-foreground">{recommendation.title}</h3>
                {recommendation.why ? (
                  <p className="text-xs leading-5 text-slate-300">
                    <span className="font-medium text-slate-200">Why: </span>
                    {recommendation.why}
                  </p>
                ) : null}
                <p className="text-xs leading-5 text-muted-foreground">
                  <span className="font-medium text-slate-300">Expected impact: </span>
                  {recommendation.expected_impact}
                </p>
              </article>
            ))}
          </div>
        )}
      </SectionCard>
    </PageSurface>
  );
}

// -------------------------------------------------------------- Explore

export function DatasetExplorePage({
  columns,
  total,
  charts,
  search,
  onSearchChange,
  preview,
}: {
  columns: DatasetColumnProfile[];
  total: number;
  charts: Record<string, ReactNode>;
  search: string;
  onSearchChange: (value: string) => void;
  preview: ReactNode;
}) {
  return (
    <PageSurface>
      <SectionCard
        title="Columns"
        description={`${total} column${total === 1 ? "" : "s"} detected. Each shows its technical type, the role the engine inferred, and the evidence behind that inference.`}
        icon={Search}
      >
        <div className="relative max-w-sm">
          <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search columns by name, type or role"
            className="ps-9"
            aria-label="Search columns"
          />
        </div>

        {columns.length === 0 ? (
          <DatasetEmptyState
            title="No columns match this search"
            reason="Clear the search to see every column in this dataset."
          />
        ) : (
          <div className="flex flex-col gap-3">
            {columns.map((column) => (
              <ColumnCard key={column.name} column={column} chart={charts[column.name]} />
            ))}
          </div>
        )}
      </SectionCard>

      {preview}
    </PageSurface>
  );
}

function ColumnCard({ column, chart }: { column: DatasetColumnProfile; chart?: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <article className={cn(CARD_GLOW_SUBTLE, "flex flex-col gap-3 p-4")}>
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip className={NEUTRAL_CHIP}>{column.technical_type}</Chip>
        <Chip className="border-violet-400/30 bg-violet-500/10 text-violet-200">
          {ROLE_LABEL[column.semantic_role]}
        </Chip>
        {column.role_confidence > 0 ? (
          <Chip className={NEUTRAL_CHIP}>
            {(column.role_confidence * 100).toFixed(0)}% confidence
          </Chip>
        ) : null}
        {column.type_mismatch_count > 0 ? (
          <Chip className={SEVERITY_STYLE.medium}>
            {formatNumber(column.type_mismatch_count)} off-type values
          </Chip>
        ) : null}
      </div>

      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="break-all text-sm font-semibold text-foreground">{column.name}</h3>
        <span className="text-[11px] text-muted-foreground">{column.role_reason}</span>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px] sm:grid-cols-4">
        <Stat label="Missing" value={`${column.null_percentage.toFixed(1)}%`} />
        <Stat label="Distinct" value={formatNumber(column.unique_count)} />
        <Stat label="Uniqueness" value={`${(column.uniqueness_ratio * 100).toFixed(0)}%`} />
        <Stat label="Non-empty" value={formatNumber(column.non_empty_count)} />
        {column.numeric ? (
          <>
            <Stat label="Min" value={formatNumber(column.numeric.minimum)} />
            <Stat label="Max" value={formatNumber(column.numeric.maximum)} />
            <Stat label="Mean" value={formatNumber(column.numeric.mean)} />
            <Stat label="Median" value={formatNumber(column.numeric.median)} />
            <Stat label="Std dev" value={formatNumber(column.numeric.standard_deviation)} />
            <Stat label="Q1" value={formatNumber(column.numeric.q1)} />
            <Stat label="Q3" value={formatNumber(column.numeric.q3)} />
            <Stat
              label="Outliers"
              value={`${formatNumber(column.numeric.outlier_count)} (${column.numeric.outlier_percentage.toFixed(1)}%)`}
            />
          </>
        ) : null}
        {column.datetime_stats ? (
          <>
            <Stat label="Earliest" value={column.datetime_stats.earliest.slice(0, 10)} />
            <Stat label="Latest" value={column.datetime_stats.latest.slice(0, 10)} />
            <Stat label="Range" value={`${formatNumber(column.datetime_stats.range_days)} days`} />
            <Stat label="Granularity" value={column.datetime_stats.granularity} />
          </>
        ) : null}
        {column.text ? (
          <>
            <Stat label="Avg length" value={`${formatNumber(column.text.average_length)} chars`} />
            <Stat label="Longest" value={`${formatNumber(column.text.maximum_length)} chars`} />
          </>
        ) : null}
      </dl>

      {column.categorical && column.categorical.top_values.length > 0 ? (
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Most frequent values
          </span>
          <div className="flex flex-col gap-1">
            {column.categorical.top_values.slice(0, 5).map((entry) => (
              <div key={entry.value} className="flex items-center gap-2 text-[11px]">
                <span className="w-32 shrink-0 truncate text-slate-300" title={entry.value}>
                  {entry.value}
                </span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
                  <div
                    className="h-full rounded-full bg-violet-500/70"
                    style={{ width: `${Math.max(entry.percentage, 1)}%` }}
                  />
                </div>
                <span className="w-16 shrink-0 text-end text-muted-foreground">
                  {entry.percentage.toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {column.sample_values.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {column.sample_values.map((value, index) => (
            <code
              key={index}
              className="max-w-full truncate rounded bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-slate-400"
            >
              {value}
            </code>
          ))}
        </div>
      ) : null}

      {chart ? (
        <div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-[11px]"
            onClick={() => setOpen((value) => !value)}
          >
            {open ? "Hide chart" : "Show chart"}
          </Button>
          {open ? <div className="mt-2">{chart}</div> : null}
        </div>
      ) : null}
    </article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium text-foreground">{value}</dd>
    </div>
  );
}

export function DatasetPreviewCard({
  columns,
  rows,
  note,
}: {
  columns: string[];
  rows: (string | null)[][];
  note: string;
}) {
  if (rows.length === 0) return null;
  return (
    <SectionCard title="Data preview" description={note} icon={Database}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-[11px]">
          <thead>
            <tr className="text-muted-foreground">
              {columns.map((column) => (
                <th key={column} className="whitespace-nowrap p-2 text-start font-medium">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-t border-white/5">
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="max-w-[180px] truncate p-2 text-slate-300">
                    {cell === null || cell === "" ? (
                      <span className="text-muted-foreground">--</span>
                    ) : (
                      cell
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}

// -------------------------------------------------------- Relationships

export function DatasetRelationshipsPage({ data }: { data: DatasetRelationshipsResponse }) {
  const { relationships, charts } = data;
  const heatmap = charts.find((chart) => chart.kind === "heatmap");
  const scatter = charts.find((chart) => chart.kind === "scatter");
  const groupCharts = charts.filter((chart) => chart.chart_id.startsWith("groups:"));

  const hasAnything =
    relationships.analyzable || relationships.group_differences.length > 0;

  return (
    <PageSurface>
      <div
        className={cn(
          CARD_GLOW_SUBTLE,
          "flex items-start gap-2 border-white/10 px-4 py-3 text-xs leading-5 text-muted-foreground",
        )}
      >
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{relationships.disclaimer}</span>
      </div>

      {!hasAnything ? (
        <DatasetEmptyState
          title="No relationship analysis is possible for this dataset"
          reason={relationships.unavailable_reason}
        />
      ) : null}

      {relationships.coverage_note ? (
        <CoverageNotice notes={[relationships.coverage_note]} />
      ) : null}

      {heatmap ? (
        <SectionCard title="Correlation matrix" icon={Sparkles}>
          <DatasetChart spec={heatmap} />
        </SectionCard>
      ) : null}

      {relationships.strongest_positive.length > 0 ||
      relationships.strongest_negative.length > 0 ? (
        <SectionCard
          title="Strongest correlations"
          description="Pearson coefficients over the paired, non-empty rows of each column."
          icon={TrendingUp}
        >
          <div className="grid gap-3 lg:grid-cols-2">
            <CorrelationList
              title="Positive"
              pairs={relationships.strongest_positive}
              tone="positive"
            />
            <CorrelationList
              title="Negative"
              pairs={relationships.strongest_negative}
              tone="negative"
            />
          </div>
        </SectionCard>
      ) : null}

      {scatter ? (
        <SectionCard title="Strongest pair, plotted" icon={TrendingUp}>
          <DatasetChart spec={scatter} />
        </SectionCard>
      ) : null}

      {relationships.group_differences.length > 0 ? (
        <SectionCard
          title="Segment differences"
          description="How each numeric metric varies across the values of a category. Groups with fewer than five rows are excluded."
          icon={Waypoints}
        >
          <div className="flex flex-col gap-3">
            {relationships.group_differences.map((difference, index) => (
              <article key={index} className={cn(CARD_GLOW_SUBTLE, "flex flex-col gap-2 p-4")}>
                <h3 className="text-sm font-semibold text-foreground">
                  {difference.metric_column} by {difference.category_column}
                </h3>
                <p className="text-xs text-muted-foreground">
                  &quot;{difference.highest_group}&quot; averages{" "}
                  {formatNumber(difference.highest_mean)} against{" "}
                  {formatNumber(difference.lowest_mean)} for &quot;{difference.lowest_group}&quot;
                  {" — a "}
                  {difference.spread_percentage.toFixed(1)}% spread. Overall average:{" "}
                  {formatNumber(difference.overall_mean)}.
                </p>
                <div className="flex flex-col gap-1">
                  {difference.groups.map((group) => (
                    <div key={group.value} className="flex items-center gap-2 text-[11px]">
                      <span className="w-28 shrink-0 truncate text-slate-300" title={group.value}>
                        {group.value}
                      </span>
                      <span className="w-16 shrink-0 text-end font-medium text-foreground">
                        {formatNumber(group.mean)}
                      </span>
                      <span
                        className={cn(
                          "w-16 shrink-0 text-end",
                          group.difference_from_overall_percentage >= 0
                            ? "text-emerald-300"
                            : "text-rose-300",
                        )}
                      >
                        {group.difference_from_overall_percentage >= 0 ? "+" : ""}
                        {group.difference_from_overall_percentage.toFixed(1)}%
                      </span>
                      <span className="w-20 shrink-0 text-end text-muted-foreground">
                        {formatNumber(group.count)} rows
                      </span>
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>
          {groupCharts.length > 0 ? <DatasetChartGrid charts={groupCharts} /> : null}
        </SectionCard>
      ) : null}

      {relationships.excluded_columns.length > 0 ? (
        <SectionCard
          title="Columns not entered into the matrix"
          description="Stated rather than silently omitted."
        >
          <ul className="flex flex-col gap-1 text-xs">
            {relationships.excluded_columns.map((entry, index) => (
              <li key={index} className="flex items-baseline justify-between gap-3">
                <span className="font-medium text-slate-300">{entry.column}</span>
                <span className="text-muted-foreground">{entry.reason}</span>
              </li>
            ))}
          </ul>
        </SectionCard>
      ) : null}
    </PageSurface>
  );
}

function CorrelationList({
  title,
  pairs,
  tone,
}: {
  title: string;
  pairs: DatasetRelationshipsResponse["relationships"]["strongest_positive"];
  tone: "positive" | "negative";
}) {
  if (pairs.length === 0) {
    return (
      <div className={cn(CARD_GLOW_SUBTLE, "p-4 text-xs text-muted-foreground")}>
        No {tone} correlation reached the reporting threshold.
      </div>
    );
  }
  return (
    <div className={cn(CARD_GLOW_SUBTLE, "flex flex-col gap-2 p-4")}>
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </span>
      {pairs.map((pair, index) => (
        <div key={index} className="flex items-baseline justify-between gap-2 text-xs">
          <span className="min-w-0 truncate text-slate-300">
            {pair.column_a} ↔ {pair.column_b}
          </span>
          <span
            className={cn(
              "shrink-0 font-semibold",
              tone === "positive" ? "text-blue-300" : "text-rose-300",
            )}
          >
            {pair.coefficient.toFixed(2)}
            <span className="ms-1 font-normal text-muted-foreground">
              ({pair.strength}, n={formatNumber(pair.sample_size)})
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}

// --------------------------------------------------------------- Trends

export function DatasetTrendsPage({ data }: { data: DatasetTrendsResponse }) {
  const { temporal, charts } = data;

  if (!temporal.analyzable) {
    return (
      <PageSurface>
        <DatasetEmptyState
          title="No temporal analysis for this dataset"
          reason={temporal.unavailable_reason}
        />
        {temporal.date_columns.length > 0 ? (
          <SectionCard title="Date columns that were considered" icon={CalendarClock}>
            <ul className="flex flex-col gap-1 text-xs">
              {temporal.date_columns.map((column) => (
                <li key={column.column} className="flex items-baseline justify-between gap-3">
                  <span className="font-medium text-slate-300">{column.column}</span>
                  <span className="text-muted-foreground">
                    {column.range_days} day range · {column.null_percentage.toFixed(1)}% missing
                  </span>
                </li>
              ))}
            </ul>
          </SectionCard>
        ) : null}
      </PageSurface>
    );
  }

  return (
    <PageSurface>
      <SectionCard
        title={`Timeline by ${temporal.primary_date_column}`}
        description={`${temporal.earliest?.slice(0, 10)} to ${temporal.latest?.slice(0, 10)} · bucketed by ${temporal.granularity}`}
        icon={CalendarClock}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricTile label="Periods" value={formatNumber(temporal.series.length)} />
          <MetricTile label="Span" value={`${formatNumber(temporal.span_days)} days`} />
          {temporal.volume_trend ? (
            <>
              <MetricTile
                label="Volume direction"
                value={temporal.volume_trend.direction}
                tone={
                  temporal.volume_trend.direction === "rising"
                    ? "text-emerald-300"
                    : temporal.volume_trend.direction === "declining"
                      ? "text-rose-300"
                      : undefined
                }
                hint={
                  temporal.volume_trend.period_over_period_percentage !== null
                    ? `${temporal.volume_trend.period_over_period_percentage > 0 ? "+" : ""}${temporal.volume_trend.period_over_period_percentage.toFixed(1)}% second half vs first`
                    : undefined
                }
              />
              <MetricTile
                label="Peak period"
                value={temporal.volume_trend.peak_period}
                hint={`${formatNumber(temporal.volume_trend.peak_value)} rows`}
              />
            </>
          ) : null}
        </div>
        {temporal.coverage_note ? <CoverageNotice notes={[temporal.coverage_note]} /> : null}
      </SectionCard>

      {charts.length > 0 ? (
        <SectionCard title="Over time" icon={TrendingUp}>
          <DatasetChartGrid charts={charts} />
        </SectionCard>
      ) : null}

      {temporal.metric_trends.length > 0 ? (
        <SectionCard
          title="Metric trends"
          description="First-half against second-half averages, which is more robust than comparing two single periods."
          icon={TrendingUp}
        >
          <div className="flex flex-col gap-3">
            {temporal.metric_trends.map((trend) => (
              <article
                key={trend.metric_column}
                className={cn(CARD_GLOW_SUBTLE, "flex flex-col gap-2 p-4")}
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <Chip
                    className={
                      trend.direction === "rising"
                        ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
                        : trend.direction === "declining"
                          ? "border-rose-400/30 bg-rose-500/10 text-rose-200"
                          : NEUTRAL_CHIP
                    }
                  >
                    {trend.direction === "rising" ? (
                      <TrendingUp className="h-3 w-3" />
                    ) : trend.direction === "declining" ? (
                      <TrendingDown className="h-3 w-3" />
                    ) : null}
                    {trend.direction}
                  </Chip>
                  {trend.period_over_period_percentage !== null ? (
                    <Chip className={NEUTRAL_CHIP}>
                      {trend.period_over_period_percentage > 0 ? "+" : ""}
                      {trend.period_over_period_percentage.toFixed(1)}% period over period
                    </Chip>
                  ) : null}
                </div>
                <h3 className="text-sm font-semibold text-foreground">{trend.metric_column}</h3>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-4">
                  <Stat label="First" value={formatNumber(trend.first_value)} />
                  <Stat label="Last" value={formatNumber(trend.last_value)} />
                  <Stat
                    label={`Peak (${trend.peak_period})`}
                    value={formatNumber(trend.peak_value)}
                  />
                  <Stat
                    label={`Low (${trend.trough_period})`}
                    value={formatNumber(trend.trough_value)}
                  />
                </dl>
              </article>
            ))}
          </div>
        </SectionCard>
      ) : null}
    </PageSurface>
  );
}

// ----------------------------------------------------------- AI Insights

function InsightCard({
  insight,
  compact = false,
}: {
  insight: DatasetInsight;
  compact?: boolean;
}) {
  return (
    <article className={cn(CARD_GLOW_SUBTLE, "flex flex-col gap-2 p-4")}>
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip className="border-violet-400/30 bg-violet-500/10 text-violet-200">
          {insight.insight_type.replace(/_/g, " ")}
        </Chip>
        <Chip className={NEUTRAL_CHIP}>{insight.confidence} confidence</Chip>
        <Chip className={NEUTRAL_CHIP}>
          {insight.generated_by === "ai" ? "AI synthesis" : "Computed"}
        </Chip>
      </div>
      <h3 className="text-sm font-semibold text-foreground">{insight.title}</h3>
      <p className="text-xs leading-5 text-slate-300">{insight.explanation}</p>
      {!compact ? (
        <>
          <div className="flex flex-col gap-1 rounded-lg border border-white/10 bg-white/[0.02] p-3">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Evidence
            </span>
            <p className="text-xs leading-5 text-slate-300">{insight.evidence}</p>
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            <span className="font-medium text-slate-300">Why it matters: </span>
            {insight.impact}
          </p>
          {insight.recommended_action ? (
            <p className="text-xs leading-5 text-violet-200/90">
              <Wrench className="mr-1 inline h-3 w-3" />
              {insight.recommended_action}
            </p>
          ) : null}
        </>
      ) : null}
    </article>
  );
}

export function DatasetInsightsPage({ data }: { data: DatasetInsightsResponse }) {
  const factLookup = useMemo(
    () => new Map(data.facts.map((fact) => [fact.fact_id, fact])),
    [data.facts],
  );

  return (
    <PageSurface>
      {data.unavailable_reason ? (
        <div
          className={cn(
            CARD_GLOW_SUBTLE,
            "flex items-start gap-2 border-amber-400/20 bg-amber-500/[0.04] px-4 py-3",
          )}
        >
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-200" />
          <p className="text-xs leading-5 text-amber-100/85">{data.unavailable_reason}</p>
        </div>
      ) : null}

      <SectionCard
        title="Insights"
        description={
          data.generated_by === "ai"
            ? "Synthesised across the measured analysis. Every insight cites the facts it rests on."
            : "Computed directly from the measured analysis. Every insight cites the facts it rests on."
        }
        icon={Sparkles}
        accent
      >
        {data.insights.length === 0 ? (
          <DatasetEmptyState
            title="No insights were produced"
            reason="This dataset did not yield enough measured evidence to state a finding."
          />
        ) : (
          <div className="flex flex-col gap-3">
            {data.insights.map((insight, index) => (
              <div key={index} className="flex flex-col gap-2">
                <InsightCard insight={insight} />
                <div className="flex flex-wrap gap-1.5 ps-1">
                  {insight.evidence_fact_ids.map((factId) => {
                    const fact = factLookup.get(factId);
                    return (
                      <span
                        key={factId}
                        title={fact?.statement ?? factId}
                        className="inline-flex max-w-full items-center gap-1 rounded border border-white/10 bg-white/[0.03] px-1.5 py-0.5 text-[10px] text-muted-foreground"
                      >
                        <span className="truncate">{fact?.statement ?? factId}</span>
                      </span>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="Executive summary"
        description="Kept short on purpose -- the detail lives on the other pages."
      >
        <div className="flex flex-col gap-3 text-sm">
          <p className="text-foreground">{data.executive_summary.scope}</p>
          <p className="text-muted-foreground">{data.executive_summary.data_health}</p>
        </div>
        {data.executive_summary.strongest_findings.length > 0 ? (
          <SummaryList
            title="Strongest findings"
            items={data.executive_summary.strongest_findings}
          />
        ) : null}
        {data.executive_summary.key_risks.length > 0 ? (
          <SummaryList title="Key risks" items={data.executive_summary.key_risks} tone="risk" />
        ) : null}
        {data.executive_summary.recommended_actions.length > 0 ? (
          <SummaryList
            title="Recommended actions"
            items={data.executive_summary.recommended_actions}
          />
        ) : null}
      </SectionCard>
    </PageSurface>
  );
}

// ------------------------------------------------------------ Text panel

export function DatasetTextPanel({ report }: { report: DatasetTextReport }) {
  if (!report.analyzable) {
    return (
      <DatasetEmptyState
        title="No text analysis for this dataset"
        reason={report.unavailable_reason}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {report.columns.map((column) => (
        <article key={column.column} className={cn(CARD_GLOW_SUBTLE, "flex flex-col gap-3 p-4")}>
          <div className="flex flex-wrap items-center gap-1.5">
            <Chip className={NEUTRAL_CHIP}>{column.column}</Chip>
          </div>

          {/* THE COVERAGE BANNER, above the numbers rather than beside them.
              Every figure in this card describes the analyzed rows only, and
              a reader who scrolls straight to "66% neutral" has to meet the
              denominator first -- otherwise a sampled result reads as a
              statement about the whole dataset. */}
          <div
            className={cn(
              "flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-[11px]",
              column.sampled
                ? "border-amber-400/25 bg-amber-500/[0.06] text-amber-100"
                : "border-white/[0.06] bg-white/[0.02] text-muted-foreground",
            )}
          >
            <Info className="h-3.5 w-3.5 shrink-0" />
            <span>
              {column.sampled ? (
                <>
                  Based on {formatNumber(column.analyzed_count)} of{" "}
                  {formatNumber(column.total_non_empty)} text rows ·{" "}
                  {column.coverage_percentage.toFixed(0)}% coverage. Figures below describe the
                  analyzed sample, not the whole dataset.
                </>
              ) : (
                <>
                  Based on all {formatNumber(column.analyzed_count)} text rows in this column ·
                  full coverage.
                </>
              )}
            </span>
          </div>

          {/* A plain, measurable comparison -- shown only when both sides
              exist, and stated without interpretation. */}
          {column.positive_to_negative_ratio !== null ? (
            <p className="text-[11px] leading-5 text-slate-300">
              <span className="font-medium text-foreground">
                Positive : Negative = {column.positive_to_negative_ratio.toFixed(2)} : 1
              </span>{" "}
              — positive responses are about {column.positive_to_negative_ratio.toFixed(1)}× as
              common as negative ones {column.sampled ? "in the analyzed sample" : "in this column"}.
            </p>
          ) : null}

          {column.sentiment_distribution.length > 0 ? (
            <div className="flex flex-col gap-1">
              {column.sentiment_distribution.map((entry) => (
                <div key={entry.sentiment} className="flex items-center gap-2 text-[11px]">
                  <span className="w-20 shrink-0 capitalize text-slate-300">{entry.sentiment}</span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
                    <div
                      className={cn(
                        "h-full rounded-full",
                        entry.sentiment === "positive"
                          ? "bg-emerald-500/70"
                          : entry.sentiment === "negative"
                            ? "bg-rose-500/70"
                            : "bg-slate-500/70",
                      )}
                      style={{ width: `${Math.max(entry.percentage, 1)}%` }}
                    />
                  </div>
                  <span className="w-16 shrink-0 text-end text-muted-foreground">
                    {entry.percentage.toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          ) : null}

          {column.themes.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {column.themes.map((theme) => (
                <Chip key={theme.term} className={NEUTRAL_CHIP}>
                  {theme.term} · {theme.rows}
                </Chip>
              ))}
            </div>
          ) : null}

          <div className="grid gap-3 lg:grid-cols-2">
            <ExampleList title="Representative positive" examples={column.positive_examples} />
            <ExampleList title="Representative negative" examples={column.negative_examples} />
            <ExampleList title="Complaints" examples={column.complaints} />
            <ExampleList title="Requests" examples={column.requests} />
          </div>
        </article>
      ))}

      {report.skipped_columns.length > 0 ? (
        <div className={cn(CARD_GLOW_SUBTLE, "flex flex-col gap-1 p-4 text-xs")}>
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Columns not analyzed as text
          </span>
          {report.skipped_columns.map((entry, index) => (
            <div key={index} className="flex items-baseline justify-between gap-3">
              <span className="font-medium text-slate-300">{entry.column}</span>
              <span className="text-muted-foreground">{entry.reason}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ExampleList({
  title,
  examples,
}: {
  title: string;
  examples: DatasetTextReport["columns"][number]["positive_examples"];
}) {
  if (examples.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </span>
      {examples.slice(0, 3).map((example) => (
        <blockquote
          key={`${title}-${example.row_number}`}
          dir="auto"
          className="rounded-lg border border-white/10 bg-white/[0.02] p-2.5 text-[11px] leading-5 text-slate-300"
        >
          <span className="me-1 text-muted-foreground">Row {example.row_number}:</span>
          {example.excerpt}
        </blockquote>
      ))}
    </div>
  );
}
