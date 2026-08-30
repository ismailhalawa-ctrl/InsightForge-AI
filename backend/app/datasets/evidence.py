"""The measured facts every dataset insight must be grounded in.

This module turns the deterministic analysis (profiles, quality,
relationships, trends, text) into a bounded, id-addressed list of FACTS. Each
fact carries the number that produced it and the statement of what that
number means.

Two things depend on this being the only channel:

  * The AI insight stage is given these facts and nothing else, and every
    insight it returns must cite at least one fact id. An insight that cites
    a fact that does not exist is rejected (see insights.py), which is what
    makes "Sales appear to be performing well" structurally impossible to
    return -- it has no fact behind it.

  * When no AI provider is available, the same facts are ranked and rendered
    directly. The deterministic analysis therefore stays genuinely useful
    with the LLM switched off, rather than degrading to an empty page.

Facts are ordered by an explicit `weight`, which is how the fallback picks
"the four most important things about this dataset" without an LLM and
without a coin toss.
"""

from dataclasses import dataclass, field

from app.datasets.contracts import NormalizedDataset
from app.datasets.profiling import ColumnProfile
from app.datasets.quality import QualityIssueType, QualityReport, QualitySeverity
from app.datasets.relationships import RelationshipReport
from app.datasets.temporal import TemporalReport
from app.datasets.text_columns import TextIntelligenceReport

# Categories a fact can belong to. Deliberately the same vocabulary the
# insight types use, so a fallback insight built from a fact inherits its
# category rather than guessing one.
FACT_SCOPE_KEY_FINDING = "key_finding"
FACT_SCOPE_QUALITY = "data_quality_risk"
FACT_SCOPE_RELATIONSHIP = "relationship"
FACT_SCOPE_SEGMENT = "segment_difference"
FACT_SCOPE_TREND = "trend"
FACT_SCOPE_ANOMALY = "anomaly"
FACT_SCOPE_TEXT = "key_finding"

# What a fact is ABOUT; several scopes share "key_finding" so scope cannot say.
FACT_CATEGORY_STRUCTURE = "structure"
FACT_CATEGORY_HEALTH = "health"
FACT_CATEGORY_QUALITY = "quality"
FACT_CATEGORY_TEXT = "text"
FACT_CATEGORY_TREND = "trend"
FACT_CATEGORY_RELATIONSHIP = "relationship"
FACT_CATEGORY_SEGMENT = "segment"
FACT_CATEGORY_DISTRIBUTION = "distribution"
FACT_CATEGORY_ANOMALY = "anomaly"

_SEVERITY_WEIGHT = {
    QualitySeverity.critical: 95.0,
    QualitySeverity.high: 80.0,
    QualitySeverity.medium: 55.0,
    QualitySeverity.low: 30.0,
}

# How many facts are handed to the provider. A prompt is a budget, and the
# top facts by weight are the ones worth spending it on.
MAX_FACTS_FOR_AI = 40


@dataclass(frozen=True)
class DatasetFact:
    fact_id: str
    scope: str
    statement: str
    weight: float
    columns: list[str] = field(default_factory=list)
    measures: dict = field(default_factory=dict)
    # CONTEXT, not a finding. The row/column count and the health score are
    # printed at the top of every dataset page, so promoting either to an
    # insight tells the reader something they are already looking at. They
    # are still supplied to the AI stage -- a model reasoning about the
    # dataset needs its size and health -- and they remain valid citations;
    # they are simply not eligible to BE an insight on their own.
    context_only: bool = False
    category: str = ""


class _FactBuilder:
    def __init__(self) -> None:
        self._facts: list[DatasetFact] = []

    def add(
        self,
        scope: str,
        statement: str,
        weight: float,
        columns: list[str] | None = None,
        measures: dict | None = None,
        context_only: bool = False,
        category: str = "",
    ) -> None:
        self._facts.append(
            DatasetFact(
                fact_id=f"f{len(self._facts) + 1}",
                scope=scope,
                statement=statement,
                weight=round(weight, 2),
                columns=columns or [],
                measures=measures or {},
                context_only=context_only,
                category=category,
            )
        )

    def build(self) -> list[DatasetFact]:
        return sorted(self._facts, key=lambda fact: fact.weight, reverse=True)


def build_facts(
    dataset: NormalizedDataset,
    profiles: list[ColumnProfile],
    quality: QualityReport,
    relationships: RelationshipReport,
    temporal: TemporalReport,
    text: TextIntelligenceReport,
) -> list[DatasetFact]:
    builder = _FactBuilder()
    total_rows = dataset.coverage.total_rows

    builder.add(
        FACT_SCOPE_KEY_FINDING,
        f"The dataset holds {total_rows:,} rows across {len(profiles)} columns "
        f"({quality.total_cells:,} cells in total).",
        40.0,
        measures={"rows": total_rows, "columns": len(profiles)},
        context_only=True,
        category=FACT_CATEGORY_STRUCTURE,
    )
    # A GOOD score is not a risk. Filing it under the quality scope made a
    # flawless dataset report "Data quality risk: the health score is
    # 100/100", which is a contradiction the reader has to unpick.
    # Read from the band rather than a second hardcoded threshold, so this
    # cannot drift away from HEALTH_BANDS the way a literal 75 already had.
    healthy = quality.health_band in ("excellent", "good") and not quality.issues
    builder.add(
        FACT_SCOPE_KEY_FINDING if healthy else FACT_SCOPE_QUALITY,
        f"The dataset health score is {quality.health_score}/100 ({quality.health_band}), "
        f"with {len(quality.issues)} quality issue(s) detected.",
        35.0 if healthy else 60.0,
        measures={"health_score": quality.health_score, "issues": len(quality.issues)},
        context_only=True,
        category=FACT_CATEGORY_HEALTH,
    )

    # WHERE the missing cells are, not merely how many. This is frequently
    # the single most useful quality statement a dataset has: "22% of cells
    # are empty" and "every empty cell belongs to two unused columns" call
    # for completely different responses.
    concentration = quality.missing_concentration
    if concentration is not None and concentration.concentrated:
        if concentration.empty_column_share_percentage >= 99.5 and concentration.empty_columns:
            names = ", ".join(f"'{name}'" for name in concentration.empty_columns)
            statement = (
                f"All {concentration.missing_cells:,} missing cells "
                f"({quality.missing_percentage:.1f}% of the dataset) come from "
                f"{len(concentration.empty_columns)} completely empty column(s): {names}."
            )
            if concentration.populated_columns_complete:
                statement += " Every remaining column is fully populated."
        else:
            named = ", ".join(
                f"'{entry['column']}' ({entry['share_of_missing']:.0f}%)"
                for entry in concentration.top_columns
            )
            statement = (
                f"{concentration.top_share_percentage:.1f}% of the "
                f"{concentration.missing_cells:,} missing cells are concentrated in "
                f"{len(concentration.top_columns)} column(s): {named}."
            )
        builder.add(
            FACT_SCOPE_QUALITY,
            statement,
            75.0,
            columns=list(concentration.empty_columns)
            or [entry["column"] for entry in concentration.top_columns],
            measures={
                "missing_cells": concentration.missing_cells,
                "top_share_percentage": concentration.top_share_percentage,
                "empty_column_share_percentage": concentration.empty_column_share_percentage,
                "empty_columns": list(concentration.empty_columns),
                "populated_columns_complete": concentration.populated_columns_complete,
            },
            category=FACT_CATEGORY_QUALITY,
        )

    # Columns the concentration fact above already accounts for. Their
    # individual issues stay in the Data Quality report -- this only stops
    # the SAME finding from being restated once per column in the insight
    # layer, which produced three near-identical "data quality risk" cards
    # for one problem.
    superseded_columns: set[str] = set()
    if (
        concentration is not None
        and concentration.concentrated
        and concentration.empty_column_share_percentage >= 99.5
    ):
        superseded_columns = set(concentration.empty_columns)

    for issue in quality.issues[:8]:
        if issue.issue_type == QualityIssueType.empty_column and issue.column in superseded_columns:
            continue
        builder.add(
            (
                FACT_SCOPE_QUALITY
                if issue.issue_type.value != "numeric_outliers"
                else FACT_SCOPE_ANOMALY
            ),
            issue.explanation,
            _SEVERITY_WEIGHT[issue.severity] * min(1.0, max(0.15, issue.affected_percentage / 100)),
            columns=[issue.column] if issue.column else [],
            measures={
                "issue_type": issue.issue_type.value,
                "severity": issue.severity.value,
                "affected_count": issue.affected_count,
                "affected_percentage": issue.affected_percentage,
            },
            category=FACT_CATEGORY_QUALITY,
        )

    for pair in (relationships.strongest_positive + relationships.strongest_negative)[:6]:
        builder.add(
            FACT_SCOPE_RELATIONSHIP,
            f"'{pair.column_a}' and '{pair.column_b}' have a {pair.strength} {pair.direction} "
            f"correlation (r = {pair.coefficient:.2f}) over {pair.sample_size:,} paired rows.",
            50.0 + 40.0 * abs(pair.coefficient),
            columns=[pair.column_a, pair.column_b],
            measures={
                "coefficient": pair.coefficient,
                "sample_size": pair.sample_size,
                "strength": pair.strength,
            },
            category=FACT_CATEGORY_RELATIONSHIP,
        )

    for difference in relationships.group_differences[:6]:
        top = difference.groups[0]
        builder.add(
            FACT_SCOPE_SEGMENT,
            f"Grouped by '{difference.category_column}', '{difference.highest_group}' has the "
            f"highest average {difference.metric_column} ({difference.highest_mean:g}, "
            f"{top['difference_from_overall_percentage']:+.1f}% versus the overall average of "
            f"{difference.overall_mean:g}), while '{difference.lowest_group}' has the lowest "
            f"({difference.lowest_mean:g}).",
            45.0 + min(45.0, abs(difference.spread_percentage) / 4),
            columns=[difference.category_column, difference.metric_column],
            measures={
                "highest_group": difference.highest_group,
                "highest_mean": difference.highest_mean,
                "lowest_group": difference.lowest_group,
                "lowest_mean": difference.lowest_mean,
                "spread_percentage": difference.spread_percentage,
                "overall_mean": difference.overall_mean,
                "group_count": len(difference.groups),
            },
            category=FACT_CATEGORY_SEGMENT,
        )

    if temporal.analyzable and temporal.volume_trend is not None:
        trend = temporal.volume_trend
        builder.add(
            FACT_SCOPE_TREND,
            f"Bucketed by {temporal.granularity} on '{temporal.primary_date_column}', row volume "
            f"is {trend.direction} -- the second half of the period averages "
            f"{trend.second_half_mean:g} rows per {temporal.granularity} against "
            f"{trend.first_half_mean:g} in the first half"
            + (
                f" ({trend.period_over_period_percentage:+.1f}%)."
                if trend.period_over_period_percentage is not None
                else "."
            ),
            70.0,
            columns=[temporal.primary_date_column or ""],
            measures={
                "direction": trend.direction,
                "period_over_period_percentage": trend.period_over_period_percentage,
                "peak_period": trend.peak_period,
                "peak_value": trend.peak_value,
                "granularity": temporal.granularity,
            },
            category=FACT_CATEGORY_TREND,
        )
        for trend in temporal.metric_trends[:4]:
            builder.add(
                FACT_SCOPE_TREND,
                f"Average '{trend.metric_column}' moved from {trend.first_value:g} in "
                f"{temporal.series[0].period} to {trend.last_value:g} in "
                f"{temporal.series[-1].period}"
                + (
                    f" ({trend.change_percentage:+.1f}%), peaking at {trend.peak_value:g} in "
                    f"{trend.peak_period}."
                    if trend.change_percentage is not None
                    else f", peaking at {trend.peak_value:g} in {trend.peak_period}."
                ),
                55.0 + min(35.0, abs(trend.change_percentage or 0) / 3),
                columns=[trend.metric_column],
                measures={
                    "first_value": trend.first_value,
                    "last_value": trend.last_value,
                    "change_percentage": trend.change_percentage,
                    "direction": trend.direction,
                },
                category=FACT_CATEGORY_TREND,
            )

    for column in text.columns:
        # Every text fact is prefixed with the population it describes, so a
        # sampled result cannot be read -- by a person or by the AI stage --
        # as a statement about the whole dataset.
        scope = (
            f"Within the analyzed sample of '{column.column}' "
            f"({column.analyzed_count:,} of {column.total_non_empty:,} text rows, "
            f"{column.coverage_percentage:.0f}% coverage)"
            if column.sampled
            else f"Across all {column.analyzed_count:,} text rows of '{column.column}'"
        )
        sample_scope = (
            f"Based on {column.analyzed_count:,} of {column.total_non_empty:,} text rows "
            f"({column.coverage_percentage:.0f}% coverage, systematic sample)."
            if column.sampled
            else f"Based on all {column.analyzed_count:,} text rows in this column."
        )

        if column.sentiment_distribution:
            top = column.sentiment_distribution[0]
            population = "the analyzed sample" if column.sampled else "all text rows"
            headline = (
                f"Most analyzed responses in '{column.column}' are {top['sentiment']}"
                if top["percentage"] > 50
                else f"The most common classification in '{column.column}' is "
                f"{top['sentiment']}"
            )
            statement = (
                f"{headline}: {top['percentage']:.1f}% of {population} was classified as "
                f"{top['sentiment']}. {sample_scope}"
            )
            if top["sentiment"] == "neutral":
                statement += (
                    " A neutral classification means the model detected no clear positive or "
                    "negative sentiment; it is not a measure of how engaged or interested the "
                    "writers were, and nothing here measures that."
                )
            builder.add(
                FACT_SCOPE_TEXT,
                statement,
                65.0,
                columns=[column.column],
                measures={
                    "dominant_sentiment": top["sentiment"],
                    "percentage": top["percentage"],
                    "analyzed_count": column.analyzed_count,
                    "total_non_empty": column.total_non_empty,
                    "coverage_percentage": column.coverage_percentage,
                    "sampled": column.sampled,
                },
                category=FACT_CATEGORY_TEXT,
            )

        # Positive against negative, stated as a plain ratio. Only when both
        # sides exist -- see TextColumnAnalysis.positive_to_negative_ratio.
        if column.positive_to_negative_ratio is not None:
            counts = {entry["sentiment"]: entry["count"] for entry in column.sentiment_distribution}
            builder.add(
                FACT_SCOPE_TEXT,
                f"{scope}, positive responses outnumber negative ones "
                f"{column.positive_to_negative_ratio:.2f} to 1 "
                f"({counts.get('positive', 0):,} positive against "
                f"{counts.get('negative', 0):,} negative).",
                55.0,
                columns=[column.column],
                measures={
                    "positive_to_negative_ratio": column.positive_to_negative_ratio,
                    "positive_count": counts.get("positive", 0),
                    "negative_count": counts.get("negative", 0),
                    "sampled": column.sampled,
                },
                category=FACT_CATEGORY_TEXT,
            )
        if column.themes:
            leading = column.themes[0]
            builder.add(
                FACT_SCOPE_TEXT,
                (
                    f"{scope}, the most recurring term is '{leading['term']}', appearing in "
                    f"{leading['rows']:,} responses ({leading['share_of_rows']:.1f}% of the sample)."
                    if column.sampled
                    else (
                        f"{scope}, the most recurring term is '{leading['term']}', appearing in "
                        f"{leading['rows']:,} responses ({leading['share_of_rows']:.1f}%)."
                    )
                ),
                45.0,
                columns=[column.column],
                measures={
                    "term": leading["term"],
                    "rows": leading["rows"],
                    "share_of_rows": leading["share_of_rows"],
                    "sampled": column.sampled,
                },
                category=FACT_CATEGORY_TEXT,
            )

    # The single most concentrated categorical dimension -- usually the most
    # quotable "X% of rows are Y" statement a dataset has.
    for profile in profiles:
        if (
            profile.is_categorical_dimension
            and profile.categorical is not None
            and profile.unique_count >= 2
            and profile.categorical.dominant_percentage >= 40
        ):
            builder.add(
                FACT_SCOPE_KEY_FINDING,
                f"'{profile.categorical.dominant_value}' accounts for "
                f"{profile.categorical.dominant_percentage:.1f}% of the non-empty values in "
                f"'{profile.name}' ({profile.unique_count:,} distinct values in total).",
                35.0 + profile.categorical.dominant_percentage / 5,
                columns=[profile.name],
                measures={
                    "value": profile.categorical.dominant_value,
                    "percentage": profile.categorical.dominant_percentage,
                    "distinct_count": profile.unique_count,
                },
                category=FACT_CATEGORY_DISTRIBUTION,
            )

    return builder.build()
