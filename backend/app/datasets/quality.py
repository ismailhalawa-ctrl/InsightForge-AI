"""Data quality detection and the Dataset Health Score.

The score is DETERMINISTIC and its rules are written down here, in one place,
as data (`_PENALTIES`). No LLM is involved at any point: a health score that
changed between two runs of the same file -- or that could not be explained
when questioned -- would be worse than no score at all.

Scoring rules
-------------
The score starts at 100 and every detected issue subtracts a penalty. Each
penalty is `weight * severity_scale`, where `weight` is the issue type's
fixed cost (below) and `severity_scale` is how much of the dataset the issue
actually affects, so one malformed cell in a million rows costs almost
nothing while a 60%-empty column costs a great deal.

    final_score = max(0, round(100 - sum(penalties)))

Bands: 90-100 excellent, 80-89 good, 65-79 fair, 40-64 poor, 0-39 critical.

`HEALTH_BANDS` is the single definition of that mapping. It is exported
because the same thresholds decide the label on the Overview, on the Data
Quality page and in History -- a second copy anywhere would eventually
disagree, and a score labelled "Good" on one screen and "Fair" on another is
worse than no label.

The arithmetic is published, not just applied: every issue carries the
`score_penalty` it contributed, and `QualityReport.scoring_rules` lists each
issue type's maximum weight alongside how much of it was actually applied.
The number is therefore auditable rather than asserted.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

from app.datasets.column_types import (
    NUMERIC_TYPES,
    SemanticRole,
    TechnicalType,
    is_blank,
    parse_datetime,
    parse_number,
)
from app.datasets.config import DatasetAnalysisConfig
from app.datasets.contracts import NormalizedDataset
from app.datasets.profiling import ColumnProfile


class QualitySeverity(StrEnum):
    """Matches SignalSeverity's existing four levels (app/models/enums.py) so
    the product has ONE severity vocabulary rather than a second one that
    means something slightly different in the same UI."""

    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class QualityIssueType(StrEnum):
    missing_values = "missing_values"
    duplicate_rows = "duplicate_rows"
    constant_column = "constant_column"
    near_constant_column = "near_constant_column"
    duplicate_identifier = "duplicate_identifier"
    inconsistent_types = "inconsistent_types"
    malformed_numeric = "malformed_numeric"
    malformed_dates = "malformed_dates"
    numeric_outliers = "numeric_outliers"
    high_cardinality = "high_cardinality"
    empty_column = "empty_column"
    whitespace_only = "whitespace_only"
    inconsistent_casing = "inconsistent_casing"
    suspicious_values = "suspicious_values"


# Fixed cost of each issue type at full severity scale. Chosen so that
# structural damage (a column with nothing in it, an id that repeats)
# outweighs cosmetic inconsistency (casing), and so that a single dataset
# cannot be driven to zero by one category of issue alone.
_PENALTIES: dict[QualityIssueType, float] = {
    QualityIssueType.empty_column: 12.0,
    QualityIssueType.duplicate_identifier: 12.0,
    QualityIssueType.missing_values: 20.0,
    QualityIssueType.duplicate_rows: 15.0,
    QualityIssueType.inconsistent_types: 10.0,
    QualityIssueType.malformed_dates: 8.0,
    QualityIssueType.malformed_numeric: 8.0,
    QualityIssueType.constant_column: 6.0,
    QualityIssueType.suspicious_values: 6.0,
    QualityIssueType.whitespace_only: 4.0,
    QualityIssueType.inconsistent_casing: 4.0,
    QualityIssueType.near_constant_column: 3.0,
    QualityIssueType.high_cardinality: 2.0,
    # Outliers are REVIEW CANDIDATES, not errors -- a genuine high-value
    # customer is an outlier and nothing is wrong with them. The penalty is
    # deliberately near-zero so flagging them never quietly condemns a
    # correct dataset.
    QualityIssueType.numeric_outliers: 1.0,
}

_SEVERITY_ORDER = {
    QualitySeverity.critical: 0,
    QualitySeverity.high: 1,
    QualitySeverity.medium: 2,
    QualitySeverity.low: 3,
}

# Above this share of a column being missing, the column is more absent than
# present and the issue escalates.
_MISSING_CRITICAL = 60.0
_MISSING_HIGH = 30.0
_MISSING_MEDIUM = 10.0

_NEAR_CONSTANT_DOMINANCE = 95.0


@dataclass(frozen=True)
class QualityIssue:
    issue_type: QualityIssueType
    severity: QualitySeverity
    column: str | None
    title: str
    explanation: str
    recommendation: str
    affected_count: int
    affected_percentage: float
    examples: list[str] = field(default_factory=list)
    # This issue's contribution to the health score, so the Data Quality page
    # can show why the number is what it is.
    score_penalty: float = 0.0


@dataclass(frozen=True)
class MissingConcentration:
    """WHERE the missing cells actually are.

    A headline "22.2% of cells are empty" reads as a dataset riddled with
    gaps. It is a completely different, and far more actionable, fact when
    every one of those cells belongs to two columns that are empty from top
    to bottom and every populated column is complete. This records that
    distribution so the page can say which of the two it is, computed
    generically from the column profiles rather than from any known dataset.
    """

    missing_cells: int
    columns_with_missing: int
    # Columns holding the missing cells, worst first, with each column's
    # share OF THE TOTAL MISSING -- not of its own column.
    top_columns: list[dict]
    # Share of all missing cells contributed by the listed top columns.
    top_share_percentage: float
    # Share contributed by columns that are empty from top to bottom.
    empty_column_share_percentage: float
    empty_columns: list[str]
    # True when every column that holds any data at all is 100% populated,
    # i.e. the missingness is entirely structural.
    populated_columns_complete: bool
    concentrated: bool


@dataclass(frozen=True)
class QualityCheck:
    """One check the engine actually ran.

    Recorded so the page can state what was verified rather than implying it.
    `status` distinguishes "ran and found nothing" from "did not apply to
    this dataset" -- reporting the second as a pass would be claiming a
    check that never happened.
    """

    check: str
    label: str
    status: str  # passed | issues_found | not_applicable
    coverage: str  # full | sampled | none
    detail: str


@dataclass(frozen=True)
class QualityReport:
    health_score: int
    health_band: str
    issues: list[QualityIssue]
    counts_by_severity: dict[str, int]
    total_cells: int
    missing_cells: int
    missing_percentage: float
    duplicate_rows: int
    duplicate_row_percentage: float
    scoring_rules: list[dict]
    missing_concentration: MissingConcentration | None = None
    checks: list[QualityCheck] = field(default_factory=list)
    # Health score if every DETERMINISTICALLY resolvable issue were fixed.
    # None when nothing is deterministically resolvable, because a
    # projection nobody can act on is a number with no meaning.
    projected_health_score: int | None = None
    projected_health_band: str | None = None
    resolvable_penalty: float = 0.0
    resolvable_issue_types: list[str] = field(default_factory=list)


# (minimum score, label), highest first. The one place the mapping lives.
HEALTH_BANDS: tuple[tuple[int, str], ...] = (
    (90, "excellent"),
    (80, "good"),
    (65, "fair"),
    (40, "poor"),
    (0, "critical"),
)


def health_band(score: int) -> str:
    for minimum, label in HEALTH_BANDS:
        if score >= minimum:
            return label
    return "critical"


def health_band_label(score: int) -> str:
    return health_band(score).capitalize()


_BAND_WORDS = frozenset(label for _, label in HEALTH_BANDS)

_BAND_IN_TEXT = re.compile(
    r"(?P<score>\b\d{1,3})\s*/\s*100\s*(?P<open>[(\[])\s*(?P<band>[A-Za-z]+)\s*(?P<close>[)\]])"
)


def canonicalize_health_band_text(text: str) -> str:
    """Re-derives any band word written beside a score from HEALTH_BANDS."""
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        written = match.group("band")
        if written.lower() not in _BAND_WORDS:
            return match.group(0)
        correct = health_band(int(match.group("score")))
        if correct == written.lower():
            return match.group(0)
        replacement = correct.capitalize() if written[:1].isupper() else correct
        original = match.group(0)
        start = match.start("band") - match.start(0)
        end = match.end("band") - match.start(0)
        return original[:start] + replacement + original[end:]

    return _BAND_IN_TEXT.sub(_replace, text)


def _band(score: int) -> str:
    return health_band(score)


def _scaled_penalty(issue_type: QualityIssueType, affected_percentage: float) -> float:
    """weight * (affected share, capped at 1.0).

    Percentage is always relative to the population the issue is about -- a
    column for column issues, the dataset for row issues -- so 100% of a
    small column and 100% of every row cost the same for the same issue
    type. That is intentional: a completely empty column is equally broken
    whichever dataset it is in.
    """
    scale = min(1.0, max(0.0, affected_percentage) / 100.0)
    return round(_PENALTIES[issue_type] * scale, 3)


def _missing_severity(percentage: float) -> QualitySeverity:
    if percentage >= _MISSING_CRITICAL:
        return QualitySeverity.critical
    if percentage >= _MISSING_HIGH:
        return QualitySeverity.high
    if percentage >= _MISSING_MEDIUM:
        return QualitySeverity.medium
    return QualitySeverity.low


def _issue(
    issue_type: QualityIssueType,
    severity: QualitySeverity,
    column: str | None,
    title: str,
    explanation: str,
    recommendation: str,
    affected_count: int,
    affected_percentage: float,
    examples: list[str] | None = None,
) -> QualityIssue:
    return QualityIssue(
        issue_type=issue_type,
        severity=severity,
        column=column,
        title=title,
        explanation=explanation,
        recommendation=recommendation,
        affected_count=affected_count,
        affected_percentage=round(affected_percentage, 2),
        examples=(examples or [])[:5],
        score_penalty=_scaled_penalty(issue_type, affected_percentage),
    )


def _casing_collisions(values: list[str]) -> list[tuple[str, list[str]]]:
    """Groups of values that differ only in case or surrounding whitespace.

    Returned rather than counted so the recommendation can name the actual
    collision ("USA / usa / USA "), which is what makes it actionable.
    """
    groups: dict[str, set[str]] = {}
    for value in values:
        groups.setdefault(value.strip().casefold(), set()).add(value)
    return [(key, sorted(variants)) for key, variants in groups.items() if len(variants) > 1]


def _detect_column_issues(
    profile: ColumnProfile,
    raw_values: list[str | None],
    total_rows: int,
    config: DatasetAnalysisConfig,
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    name = profile.name

    if profile.technical_type == TechnicalType.empty or profile.non_empty_count == 0:
        issues.append(
            _issue(
                QualityIssueType.empty_column,
                QualitySeverity.high,
                name,
                f"'{name}' contains no values",
                # Names the column. This explanation is read standalone in
                # Key Risks, in insights, and in the facts the AI provider
                # sees -- "this column" identifies nothing in any of them.
                f"Every one of the {profile.analyzed_count:,} analyzed rows is empty in "
                f"'{name}'.",
                f"Remove '{name}', or confirm whether the export that produced this file was "
                "supposed to populate it.",
                profile.analyzed_count,
                100.0,
            )
        )
        return issues

    if profile.null_percentage > 0:
        issues.append(
            _issue(
                QualityIssueType.missing_values,
                _missing_severity(profile.null_percentage),
                name,
                f"'{name}' is {profile.null_percentage:.1f}% missing",
                f"{profile.null_count:,} of {total_rows:,} rows have no value in '{name}'.",
                (
                    "Investigate why these rows are blank before using this column in any "
                    "aggregate -- a mean over the remaining values silently excludes them."
                    if profile.null_percentage >= _MISSING_MEDIUM
                    else "Low enough to work with; drop or impute the blanks when this column "
                    "is used in a calculation."
                ),
                profile.null_count,
                profile.null_percentage,
            )
        )

    if profile.unique_count == 1:
        issues.append(
            _issue(
                QualityIssueType.constant_column,
                QualitySeverity.medium,
                name,
                f"'{name}' has a single value throughout",
                f"Every non-empty row of '{name}' holds "
                f"'{profile.sample_values[0] if profile.sample_values else ''}'. "
                "A column with no variation cannot explain, split or predict anything.",
                f"Remove '{name}' from the analysis, or check whether a filter was applied "
                "before the file was exported.",
                profile.non_empty_count,
                100.0,
                profile.sample_values[:1],
            )
        )
    elif (
        profile.categorical is not None
        and profile.categorical.dominant_percentage >= _NEAR_CONSTANT_DOMINANCE
    ):
        issues.append(
            _issue(
                QualityIssueType.near_constant_column,
                QualitySeverity.low,
                name,
                f"'{name}' is dominated by one value",
                f"'{profile.categorical.dominant_value}' accounts for "
                f"{profile.categorical.dominant_percentage:.1f}% of non-empty values, leaving very "
                "little variation to analyze.",
                "Treat comparisons across this column with caution -- the minority groups may be "
                "too small to support a conclusion.",
                int(profile.non_empty_count * profile.categorical.dominant_percentage / 100),
                profile.categorical.dominant_percentage,
            )
        )

    if profile.semantic_role == SemanticRole.identifier and profile.non_empty_count > 0:
        duplicate_ids = profile.non_empty_count - profile.unique_count
        if duplicate_ids > 0:
            percentage = 100 * duplicate_ids / profile.non_empty_count
            issues.append(
                _issue(
                    QualityIssueType.duplicate_identifier,
                    QualitySeverity.high,
                    name,
                    f"'{name}' repeats values despite reading as an identifier",
                    f"{duplicate_ids:,} of {profile.non_empty_count:,} values in '{name}' are not "
                    "unique. If this column is meant to identify a row, the file contains either "
                    "duplicates or a broken key.",
                    f"Check whether '{name}' is genuinely the key for this dataset before joining "
                    "or de-duplicating on it.",
                    duplicate_ids,
                    percentage,
                )
            )

    if profile.type_mismatch_count > 0:
        percentage = 100 * profile.type_mismatch_count / max(1, profile.non_empty_count)
        if profile.technical_type in NUMERIC_TYPES:
            issue_type = QualityIssueType.malformed_numeric
            title = f"'{name}' contains values that are not numbers"
            explanation = (
                f"{profile.type_mismatch_count:,} of {profile.non_empty_count:,} values in this "
                "otherwise numeric column could not be read as a number."
            )
            recommendation = (
                "Convert or blank these entries -- placeholders such as 'N/A' silently reduce the "
                "population every statistic on this column is computed over."
            )
        elif profile.technical_type == TechnicalType.datetime:
            issue_type = QualityIssueType.malformed_dates
            title = f"'{name}' contains values that are not dates"
            explanation = (
                f"{profile.type_mismatch_count:,} of {profile.non_empty_count:,} values in this "
                "date column did not parse in any recognised format."
            )
            recommendation = "Normalise these to ISO 8601 (YYYY-MM-DD) so they join the timeline."
        else:
            issue_type = QualityIssueType.inconsistent_types
            title = f"'{name}' mixes value shapes"
            explanation = (
                f"{profile.type_mismatch_count:,} values do not match the dominant shape of this "
                "column."
            )
            recommendation = "Decide what this column is meant to hold and normalise the outliers."
        issues.append(
            _issue(
                issue_type,
                QualitySeverity.medium if percentage < 20 else QualitySeverity.high,
                name,
                title,
                explanation,
                recommendation,
                profile.type_mismatch_count,
                percentage,
                profile.type_mismatch_examples,
            )
        )

    # A string column split roughly between numbers and words is a different
    # defect from a numeric column with a few strays: neither shape won, so
    # detect_technical_type never produced mismatches to report.
    if profile.technical_type in (TechnicalType.categorical, TechnicalType.text):
        non_empty = [value.strip() for value in raw_values if not is_blank(value)]
        numeric_like = sum(1 for value in non_empty if parse_number(value) is not None)
        if non_empty and 0.15 <= numeric_like / len(non_empty) <= 0.85:
            percentage = 100 * numeric_like / len(non_empty)
            issues.append(
                _issue(
                    QualityIssueType.inconsistent_types,
                    QualitySeverity.high,
                    name,
                    f"'{name}' mixes numbers and text",
                    f"{numeric_like:,} of {len(non_empty):,} values parse as numbers and the rest "
                    "do not, so this column has no single type.",
                    f"Split '{name}' into separate fields, or normalise it to one type before "
                    "using it in any calculation.",
                    numeric_like,
                    percentage,
                    [value for value in non_empty if parse_number(value) is None][:3],
                )
            )

        # Values named like a date that do not parse as one -- the column
        # fell through to text, so the malformed-dates branch above never
        # saw it.
        if profile.role_reason.startswith("Named like a date"):
            unparsed = [value for value in non_empty if parse_datetime(value) is None]
            if unparsed:
                percentage = 100 * len(unparsed) / len(non_empty)
                issues.append(
                    _issue(
                        QualityIssueType.malformed_dates,
                        QualitySeverity.high,
                        name,
                        f"'{name}' is named as a date but does not parse as one",
                        f"{len(unparsed):,} of {len(non_empty):,} values could not be read as a "
                        "date, so this column cannot be used as a time dimension.",
                        "Normalise to ISO 8601 (YYYY-MM-DD) to unlock trend analysis on this "
                        "column.",
                        len(unparsed),
                        percentage,
                        unparsed[:3],
                    )
                )

    whitespace_only = sum(
        1 for value in raw_values if value is not None and value != "" and not value.strip()
    )
    if whitespace_only:
        percentage = 100 * whitespace_only / max(1, profile.analyzed_count)
        issues.append(
            _issue(
                QualityIssueType.whitespace_only,
                QualitySeverity.low,
                name,
                f"'{name}' has whitespace-only cells",
                f"{whitespace_only:,} cells contain only spaces or tabs. These read as populated "
                "in most tools but carry no value.",
                "Normalise whitespace-only cells to empty so missing-data counts are honest.",
                whitespace_only,
                percentage,
            )
        )

    if profile.categorical is not None and profile.technical_type == TechnicalType.categorical:
        non_empty = [value.strip() for value in raw_values if not is_blank(value)]
        collisions = _casing_collisions([value for value in raw_values if not is_blank(value)])
        if collisions:
            counts = Counter(value for value in raw_values if not is_blank(value))
            affected = sum(
                sum(counts[variant] for variant in variants) for _key, variants in collisions
            )
            percentage = 100 * affected / max(1, len(non_empty))
            issues.append(
                _issue(
                    QualityIssueType.inconsistent_casing,
                    QualitySeverity.medium,
                    name,
                    f"'{name}' has values that differ only in case or spacing",
                    f"{len(collisions)} group(s) of values in '{name}' are the same label "
                    f"written differently, affecting {affected:,} rows. They are counted as "
                    "separate categories.",
                    f"Trim and case-normalise '{name}' so each real category is counted once.",
                    affected,
                    percentage,
                    [" / ".join(variants) for _key, variants in collisions[:3]],
                )
            )

        if (
            profile.uniqueness_ratio >= config.high_cardinality_ratio
            and profile.unique_count > config.top_categories
        ):
            issues.append(
                _issue(
                    QualityIssueType.high_cardinality,
                    QualitySeverity.low,
                    name,
                    f"'{name}' has very high cardinality",
                    f"{profile.unique_count:,} distinct values across {profile.non_empty_count:,} "
                    "rows. Grouping by this column produces almost as many groups as rows.",
                    "Group into broader buckets before charting or segmenting on this column.",
                    profile.unique_count,
                    100 * profile.uniqueness_ratio,
                )
            )

    # Outliers are only meaningful for a MEASURE. An identifier column is
    # numeric by shape but not by meaning -- a customer id far from the
    # others is a customer id, not an anomaly, and reporting it teaches the
    # user to ignore this section.
    if (
        profile.numeric is not None
        and profile.numeric.outlier_count > 0
        and profile.semantic_role != SemanticRole.identifier
    ):
        issues.append(
            _issue(
                QualityIssueType.numeric_outliers,
                QualitySeverity.low,
                name,
                f"'{name}' has {profile.numeric.outlier_count:,} unusual values",
                f"{profile.numeric.outlier_count:,} values in '{name}' fall outside "
                f"[{profile.numeric.lower_bound:g}, {profile.numeric.upper_bound:g}] "
                f"(Tukey fences at {config.outlier_iqr_multiplier}x IQR). These are review "
                "candidates, not necessarily errors.",
                "Review these rows before deciding whether they are genuine extremes or data "
                "entry mistakes.",
                profile.numeric.outlier_count,
                profile.numeric.outlier_percentage,
                [str(value) for value in profile.numeric.outlier_examples],
            )
        )

        # A negative value in a column that can only be non-negative by
        # definition. Restricted to counts, ages and quantities so this
        # never becomes domain guessing -- a temperature or a balance is
        # legitimately negative and is not flagged.
        lowered = profile.name.lower()
        if profile.numeric.minimum < 0 and any(
            token in lowered for token in ("age", "count", "quantity", "qty", "duration")
        ):
            negatives = sum(
                1
                for value in raw_values
                if not is_blank(value)
                and (parsed := parse_number(value.strip())) is not None
                and parsed < 0
            )
            if negatives:
                percentage = 100 * negatives / max(1, profile.non_empty_count)
                issues.append(
                    _issue(
                        QualityIssueType.suspicious_values,
                        QualitySeverity.high,
                        name,
                        f"'{name}' contains negative values",
                        f"{negatives:,} rows hold a negative value in a column whose name implies "
                        "it cannot be negative.",
                        "Check the source of these rows -- a negative here usually means a sign "
                        "error or a sentinel value.",
                        negatives,
                        percentage,
                    )
                )

    return issues


# Issues whose recommended fix has a KNOWN, exact effect on the score.
#
# Dropping an empty column removes its penalty and nothing else -- no other
# metric in the report is derived from it. De-duplicating removes exactly the
# duplicate-row penalty. Trimming whitespace and normalising casing likewise
# resolve their own issue completely.
#
# Deliberately excludes missing_values, outliers, duplicate identifiers and
# mixed types: each is resolved by a human DECISION (impute or drop? genuine
# extreme or error?), and the resulting score depends on which decision is
# taken. Projecting those would be guessing.
_DETERMINISTICALLY_RESOLVABLE = frozenset(
    {
        QualityIssueType.empty_column,
        QualityIssueType.duplicate_rows,
        QualityIssueType.whitespace_only,
        QualityIssueType.inconsistent_casing,
    }
)

# How many columns the concentration summary names before it stops.
_MAX_CONCENTRATION_COLUMNS = 5

# At or above this share of all missing cells coming from the named columns,
# the missingness is "concentrated" rather than spread across the dataset.
_CONCENTRATION_THRESHOLD = 80.0


def _missing_concentration(
    profiles: list[ColumnProfile], total_missing: int
) -> MissingConcentration | None:
    """Which columns the missing cells belong to, as shares of the total.

    Computed from the per-column null counts the profiler already produced,
    so this adds no new measurement -- it answers a question the existing
    numbers could already answer but nothing was asking.
    """
    if total_missing <= 0 or not profiles:
        return None

    with_missing = sorted(
        (profile for profile in profiles if profile.null_count > 0),
        key=lambda profile: profile.null_count,
        reverse=True,
    )
    if not with_missing:
        return None

    top = with_missing[:_MAX_CONCENTRATION_COLUMNS]
    top_missing = sum(profile.null_count for profile in top)
    empty_columns = [profile for profile in with_missing if profile.null_percentage >= 100.0]
    empty_missing = sum(profile.null_count for profile in empty_columns)

    # Every column that holds ANY data is completely populated -- so the
    # missingness is structural (whole columns absent), not scattered.
    populated_complete = all(
        profile.null_count == 0 for profile in profiles if profile.null_percentage < 100.0
    )

    return MissingConcentration(
        missing_cells=total_missing,
        columns_with_missing=len(with_missing),
        top_columns=[
            {
                "column": profile.name,
                "missing_count": profile.null_count,
                "analyzed_rows": profile.analyzed_count,
                "missing_percentage_of_column": profile.null_percentage,
                "share_of_missing": round(100 * profile.null_count / total_missing, 2),
                "entirely_empty": profile.null_percentage >= 100.0,
            }
            for profile in top
        ],
        top_share_percentage=round(100 * top_missing / total_missing, 2),
        empty_column_share_percentage=round(100 * empty_missing / total_missing, 2),
        empty_columns=[profile.name for profile in empty_columns],
        populated_columns_complete=populated_complete and bool(empty_columns),
        concentrated=(100 * top_missing / total_missing) >= _CONCENTRATION_THRESHOLD,
    )


def _build_checks(
    profiles: list[ColumnProfile],
    issues: list[QualityIssue],
    dataset: NormalizedDataset,
) -> list[QualityCheck]:
    """What was actually verified, and with what outcome.

    `not_applicable` is a distinct status on purpose: a dataset with no date
    column did not PASS a date-validity check, it never ran one, and
    reporting that as a pass would claim a check that did not happen.
    """
    found = {issue.issue_type for issue in issues}
    row_coverage = "sampled" if dataset.coverage.sampled else "full"

    has_numeric = any(profile.is_numeric_metric for profile in profiles)
    has_categorical = any(profile.is_categorical_dimension for profile in profiles)
    has_dates = any(profile.is_temporal for profile in profiles)
    has_identifier = any(profile.semantic_role == SemanticRole.identifier for profile in profiles)

    def check(key, label, issue_types, applicable, coverage, detail_passed, detail_na):
        if not applicable:
            return QualityCheck(key, label, "not_applicable", "none", detail_na)
        if issue_types & found:
            count = sum(1 for issue in issues if issue.issue_type in issue_types)
            return QualityCheck(key, label, "issues_found", coverage, f"{count} issue(s) found")
        return QualityCheck(key, label, "passed", coverage, detail_passed)

    return [
        check(
            "missing_values",
            "Missing values",
            {QualityIssueType.missing_values},
            True,
            "full",
            # Wording depends on whether whole columns are empty. Saying "no
            # column has missing values" on a dataset whose cells ARE partly
            # empty would be false -- what passed is the scattered-gaps
            # check; the empty columns are reported by their own check.
            (
                "No populated column has missing values"
                if any(profile.null_percentage >= 100.0 for profile in profiles)
                else "No column has missing values"
            ),
            "",
        ),
        check(
            "duplicate_rows",
            "Duplicate rows",
            {QualityIssueType.duplicate_rows},
            True,
            "full" if dataset.coverage.duplicate_detection_complete else "sampled",
            "No duplicate rows detected",
            "",
        ),
        check(
            "empty_columns",
            "Empty and constant columns",
            {QualityIssueType.empty_column, QualityIssueType.constant_column},
            True,
            row_coverage,
            "Every column carries varying data",
            "",
        ),
        check(
            "type_consistency",
            "Type consistency",
            {QualityIssueType.inconsistent_types, QualityIssueType.malformed_numeric},
            True,
            row_coverage,
            "No type inconsistencies detected",
            "",
        ),
        check(
            "category_consistency",
            "Category consistency",
            {QualityIssueType.inconsistent_casing, QualityIssueType.high_cardinality},
            has_categorical,
            row_coverage,
            "No casing or spacing collisions detected",
            "No categorical column to check",
        ),
        check(
            "identifier_integrity",
            "Identifier integrity",
            {QualityIssueType.duplicate_identifier},
            has_identifier,
            row_coverage,
            "Identifier values are unique",
            "No identifier column detected",
        ),
        check(
            "date_validity",
            "Date validity",
            {QualityIssueType.malformed_dates},
            has_dates,
            row_coverage,
            "No malformed dates detected",
            "No date column to check",
        ),
        check(
            "outliers",
            "Numeric outliers",
            {QualityIssueType.numeric_outliers, QualityIssueType.suspicious_values},
            has_numeric,
            row_coverage,
            "No numeric outliers detected",
            "No numeric measure to check",
        ),
        check(
            "whitespace",
            "Whitespace-only cells",
            {QualityIssueType.whitespace_only},
            True,
            row_coverage,
            "No whitespace-only cells detected",
            "",
        ),
    ]


def _projection(issues, score):
    """The score this dataset would have if every deterministically
    resolvable issue were fixed.

    Exact arithmetic over penalties that are already published -- not an
    estimate, and deliberately not a model. Returns None when nothing is
    deterministically resolvable, rather than a projection equal to the
    current score, which would read as "fixing things changes nothing".
    """
    resolvable = [issue for issue in issues if issue.issue_type in _DETERMINISTICALLY_RESOLVABLE]
    if not resolvable:
        return None, 0.0, []
    recovered = round(sum(issue.score_penalty for issue in resolvable), 3)
    projected = max(0, min(100, round(score + recovered)))
    return projected, recovered, sorted({issue.issue_type.value for issue in resolvable})


def build_quality_report(
    dataset: NormalizedDataset,
    profiles: list[ColumnProfile],
    config: DatasetAnalysisConfig,
) -> QualityReport:
    issues: list[QualityIssue] = []

    total_rows = dataset.coverage.total_rows

    if total_rows == 0:
        # A headers-only file. Reported once, as the one thing that is
        # actually wrong -- running the per-column checks here would produce
        # "this column contains no values" for every column, which is a
        # column-shaped restatement of a file-shaped problem.
        return QualityReport(
            health_score=0,
            health_band=_band(0),
            issues=[
                _issue(
                    QualityIssueType.empty_column,
                    QualitySeverity.critical,
                    None,
                    "The dataset has no data rows",
                    f"{len(dataset.columns)} column header(s) were read, but the file contains no "
                    "rows beneath them.",
                    "Check the export that produced this file -- there is nothing here to "
                    "analyze.",
                    0,
                    100.0,
                )
            ],
            counts_by_severity={
                severity.value: (1 if severity == QualitySeverity.critical else 0)
                for severity in QualitySeverity
            },
            total_cells=0,
            missing_cells=0,
            missing_percentage=0.0,
            duplicate_rows=0,
            duplicate_row_percentage=0.0,
            scoring_rules=[
                {"issue_type": issue_type.value, "max_penalty": penalty, "applied": 0.0}
                for issue_type, penalty in _PENALTIES.items()
            ],
        )

    duplicates = dataset.coverage.exact_duplicate_rows
    if duplicates > 0 and total_rows > 0:
        percentage = 100 * duplicates / total_rows
        issues.append(
            _issue(
                QualityIssueType.duplicate_rows,
                QualitySeverity.high if percentage >= 5 else QualitySeverity.medium,
                None,
                f"{duplicates:,} duplicate row" + ("s" if duplicates != 1 else ""),
                f"{duplicates:,} of {total_rows:,} rows are exact copies of an earlier row across "
                "every column"
                + (
                    " (lower bound -- duplicate detection was capped)."
                    if not dataset.coverage.duplicate_detection_complete
                    else "."
                ),
                "De-duplicate before aggregating -- every count, sum and average in this dataset "
                "currently counts these rows more than once.",
                duplicates,
                percentage,
            )
        )

    for profile in profiles:
        issues.extend(
            _detect_column_issues(profile, dataset.column_values(profile.index), total_rows, config)
        )

    issues.sort(key=lambda issue: (_SEVERITY_ORDER[issue.severity], -issue.score_penalty))

    total_penalty = sum(issue.score_penalty for issue in issues)
    score = max(0, round(100 - total_penalty))

    total_cells = total_rows * len(dataset.columns)
    missing_cells = dataset.coverage.exact_missing_cells
    projected, recovered, resolvable_types = _projection(issues, score)

    return QualityReport(
        health_score=score,
        health_band=_band(score),
        missing_concentration=_missing_concentration(profiles, missing_cells),
        checks=_build_checks(profiles, issues, dataset),
        projected_health_score=projected,
        projected_health_band=(_band(projected) if projected is not None else None),
        resolvable_penalty=recovered,
        resolvable_issue_types=resolvable_types,
        issues=issues,
        counts_by_severity={
            severity.value: sum(1 for issue in issues if issue.severity == severity)
            for severity in QualitySeverity
        },
        total_cells=total_cells,
        missing_cells=missing_cells,
        missing_percentage=(round(100 * missing_cells / total_cells, 2) if total_cells else 0.0),
        duplicate_rows=duplicates,
        duplicate_row_percentage=(round(100 * duplicates / total_rows, 2) if total_rows else 0.0),
        scoring_rules=[
            {
                "issue_type": issue_type.value,
                "max_penalty": penalty,
                "applied": round(
                    sum(issue.score_penalty for issue in issues if issue.issue_type == issue_type),
                    3,
                ),
            }
            for issue_type, penalty in _PENALTIES.items()
        ],
    )
