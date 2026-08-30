"""Cleaning RECOMMENDATIONS -- never cleaning.

The uploaded file is not modified, and no cleaned copy is written. This
sprint produces a list of actions a person (or a later one-click cleaning
feature) could take, each carrying the evidence that justifies it and an
honest statement of what it would change.

Each recommendation names a machine-readable `action` alongside its prose.
That field is the seam a future automated-cleaning sprint plugs into: it can
execute the same list this page displays, so what the user was shown and
what would run cannot drift apart.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from app.datasets.quality import QualityIssue, QualityIssueType, QualityReport, QualitySeverity


class CleaningAction(StrEnum):
    remove_duplicate_rows = "remove_duplicate_rows"
    fill_or_drop_missing = "fill_or_drop_missing"
    drop_column = "drop_column"
    normalize_category_casing = "normalize_category_casing"
    trim_whitespace = "trim_whitespace"
    convert_to_datetime = "convert_to_datetime"
    convert_to_number = "convert_to_number"
    review_outliers = "review_outliers"
    review_duplicate_identifiers = "review_duplicate_identifiers"
    split_mixed_column = "split_mixed_column"
    review_suspicious_values = "review_suspicious_values"
    bucket_high_cardinality = "bucket_high_cardinality"


class Applicability(StrEnum):
    """How safely this action could be applied without a human decision.

    `safe` -- reversible and semantics-preserving (trimming whitespace).
    `review` -- changes what the data says and needs a judgement call
                (dropping rows, imputing values).
    `manual` -- cannot be automated at all; the fix depends on knowledge
                that is not in the file.
    """

    safe = "safe"
    review = "review"
    manual = "manual"


@dataclass(frozen=True)
class CleaningRecommendation:
    action: CleaningAction
    applicability: Applicability
    column: str | None
    title: str
    reason: str
    affected_data: str
    why: str
    expected_impact: str
    affected_count: int
    affected_percentage: float
    severity: QualitySeverity
    source_issue: QualityIssueType
    examples: list[str] = field(default_factory=list)


# One issue type maps to one action. Kept as data rather than a chain of
# branches so a new quality check can be given a remediation by adding a row
# here, and so the set of actions stays enumerable for the future automated
# cleaner.
_ACTION_FOR_ISSUE: dict[QualityIssueType, tuple[CleaningAction, Applicability]] = {
    QualityIssueType.duplicate_rows: (
        CleaningAction.remove_duplicate_rows,
        Applicability.review,
    ),
    QualityIssueType.missing_values: (CleaningAction.fill_or_drop_missing, Applicability.review),
    QualityIssueType.empty_column: (CleaningAction.drop_column, Applicability.safe),
    QualityIssueType.constant_column: (CleaningAction.drop_column, Applicability.review),
    QualityIssueType.inconsistent_casing: (
        CleaningAction.normalize_category_casing,
        Applicability.safe,
    ),
    QualityIssueType.whitespace_only: (CleaningAction.trim_whitespace, Applicability.safe),
    QualityIssueType.malformed_dates: (CleaningAction.convert_to_datetime, Applicability.review),
    QualityIssueType.malformed_numeric: (CleaningAction.convert_to_number, Applicability.review),
    QualityIssueType.numeric_outliers: (CleaningAction.review_outliers, Applicability.manual),
    QualityIssueType.duplicate_identifier: (
        CleaningAction.review_duplicate_identifiers,
        Applicability.manual,
    ),
    QualityIssueType.inconsistent_types: (CleaningAction.split_mixed_column, Applicability.manual),
    QualityIssueType.suspicious_values: (
        CleaningAction.review_suspicious_values,
        Applicability.manual,
    ),
    QualityIssueType.high_cardinality: (
        CleaningAction.bucket_high_cardinality,
        Applicability.review,
    ),
}

_WHY: dict[CleaningAction, str] = {
    CleaningAction.remove_duplicate_rows: (
        "Repeated rows are counted more than once by every aggregate, so they bias results "
        "before any analysis begins."
    ),
    CleaningAction.fill_or_drop_missing: (
        "Gaps handled implicitly mean each statistic is computed over a different population "
        "without saying so."
    ),
    CleaningAction.drop_column: (
        "The column holds no values, so nothing downstream can read anything from it -- it only "
        "inflates the dataset's missing-cell count."
    ),
    CleaningAction.normalize_category_casing: (
        "Labels that differ only by case or spacing split one real category into several."
    ),
    CleaningAction.trim_whitespace: (
        "Cells holding only spaces look populated to a reader and empty to an analysis."
    ),
    CleaningAction.convert_to_datetime: (
        "Stored as text, the column cannot be ordered or bucketed, so no trend can be computed "
        "from it."
    ),
    CleaningAction.convert_to_number: (
        "Numeric-looking text is skipped by every numeric statistic, silently narrowing the "
        "population each figure describes."
    ),
    CleaningAction.review_outliers: (
        "Whether these are genuine extremes or errors decides which summary of the column is "
        "honest, and only a person who knows the data can say which."
    ),
    CleaningAction.review_duplicate_identifiers: (
        "A key with repeats is either not a key or evidence of duplicated records; the two need "
        "opposite responses."
    ),
    CleaningAction.split_mixed_column: (
        "A column holding more than one kind of value cannot be typed, so it is excluded from "
        "statistics entirely."
    ),
    CleaningAction.review_suspicious_values: (
        "These values do not match what the column name describes, so any figure derived from "
        "the column may be measuring something else."
    ),
    CleaningAction.bucket_high_cardinality: (
        "A dimension with almost as many values as rows cannot group anything."
    ),
}

_IMPACT: dict[CleaningAction, str] = {
    CleaningAction.remove_duplicate_rows: (
        "Every count, sum and average in the dataset would change, because duplicated rows are "
        "currently counted more than once."
    ),
    CleaningAction.fill_or_drop_missing: (
        "Statistics on this column would be computed over a stated population instead of an "
        "implicit one."
    ),
    CleaningAction.drop_column: "No analysis would lose information -- this column carries none.",
    CleaningAction.normalize_category_casing: (
        "Category counts and every chart grouped by this column would merge the duplicated labels."
    ),
    CleaningAction.trim_whitespace: (
        "Missing-value counts would become accurate; nothing else changes."
    ),
    CleaningAction.convert_to_datetime: (
        "This column would become usable as a time dimension, enabling trend analysis."
    ),
    CleaningAction.convert_to_number: (
        "These rows would re-enter the mean, median and correlation calculations they are "
        "currently excluded from."
    ),
    CleaningAction.review_outliers: (
        "No automatic change. Confirming whether these are genuine extremes decides whether the "
        "mean or the median is the honest summary of this column."
    ),
    CleaningAction.review_duplicate_identifiers: (
        "No automatic change. Whether this column is a valid key decides whether the dataset can "
        "be joined or de-duplicated on it."
    ),
    CleaningAction.split_mixed_column: (
        "Splitting into typed fields would make this column usable in statistics for the first "
        "time."
    ),
    CleaningAction.review_suspicious_values: (
        "No automatic change. These rows either encode something the column name does not "
        "describe, or they are errors."
    ),
    CleaningAction.bucket_high_cardinality: (
        "Charts and segment comparisons on this column would become readable instead of showing "
        "one bar per row."
    ),
}


def build_cleaning_recommendations(report: QualityReport) -> list[CleaningRecommendation]:
    """One recommendation per detected issue, ordered by severity then reach.

    Derived entirely from the quality report rather than re-scanning the
    data: a recommendation the Data Quality page cannot point at an issue for
    would be a suggestion with no evidence behind it.
    """
    recommendations: list[CleaningRecommendation] = []
    for issue in report.issues:
        mapped = _ACTION_FOR_ISSUE.get(issue.issue_type)
        if mapped is None:
            continue
        action, applicability = mapped
        recommendations.append(
            CleaningRecommendation(
                action=action,
                applicability=applicability,
                column=issue.column,
                title=_title_for(action, issue),
                reason=issue.explanation,
                affected_data=(
                    f"{issue.affected_count:,} rows"
                    if issue.column is None
                    else f"{issue.affected_count:,} values in '{issue.column}'"
                ),
                why=_WHY[action],
                expected_impact=_IMPACT[action],
                affected_count=issue.affected_count,
                affected_percentage=issue.affected_percentage,
                severity=issue.severity,
                source_issue=issue.issue_type,
                examples=issue.examples,
            )
        )
    return recommendations


def _title_for(action: CleaningAction, issue: QualityIssue) -> str:
    column = issue.column
    titles: dict[CleaningAction, str] = {
        CleaningAction.remove_duplicate_rows: (
            f"Remove {issue.affected_count:,} duplicate row"
            + ("s" if issue.affected_count != 1 else "")
        ),
        CleaningAction.fill_or_drop_missing: f"Decide how to handle missing values in '{column}'",
        CleaningAction.drop_column: f"Remove '{column}'",
        CleaningAction.normalize_category_casing: f"Normalise casing and spacing in '{column}'",
        CleaningAction.trim_whitespace: f"Trim whitespace-only cells in '{column}'",
        CleaningAction.convert_to_datetime: f"Convert '{column}' to a real date format",
        CleaningAction.convert_to_number: f"Convert numeric-looking text in '{column}'",
        CleaningAction.review_outliers: f"Review {issue.affected_count:,} unusual values in '{column}'",
        CleaningAction.review_duplicate_identifiers: f"Inspect duplicate identifiers in '{column}'",
        CleaningAction.split_mixed_column: f"Split or normalise the mixed column '{column}'",
        CleaningAction.review_suspicious_values: f"Review suspicious values in '{column}'",
        CleaningAction.bucket_high_cardinality: f"Group '{column}' into broader buckets",
    }
    return titles[action]
