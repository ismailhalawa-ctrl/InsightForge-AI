"""Converts the engine's dataclasses into the persisted/API schema, once.

`dataclasses.asdict` is deliberately not used. It would recurse into enums,
datetimes and nested dataclasses and produce a shape that happens to work
today and silently drifts tomorrow; routing everything through the pydantic
response models means the stored JSON is validated against the same contract
the API serves, so an analysis that persisted successfully is an analysis
that will load.
"""

from app.datasets.charts import ChartSpec
from app.datasets.cleaning import CleaningRecommendation
from app.datasets.engine import DatasetAnalysis as EngineAnalysis
from app.datasets.evidence import DatasetFact
from app.datasets.insights import DatasetInsightResult
from app.datasets.profiling import ColumnProfile
from app.datasets.quality import QualityReport
from app.datasets.relationships import RelationshipReport
from app.datasets.temporal import TemporalReport
from app.datasets.text_columns import TextIntelligenceReport
from app.schemas.dataset_intelligence import (
    CategoricalStatisticsResponse,
    MissingConcentrationResponse,
    QualityCheckResponse,
    ChartSpecResponse,
    CleaningRecommendationResponse,
    ColumnProfileResponse,
    CorrelationPairResponse,
    DatasetCapabilityAvailability,
    DatasetCoverageResponse,
    DatasetFactResponse,
    DatasetInsightResponse,
    DatasetInsightsResponse,
    DatasetOverviewResponse,
    DatasetPreviewResponse,
    DatetimeStatisticsResponse,
    ExecutiveSummaryResponse,
    GroupDifferenceResponse,
    MetricTrendResponse,
    NumericStatisticsResponse,
    QualityIssueResponse,
    QualityReportResponse,
    RelationshipReportResponse,
    TemporalReportResponse,
    TextColumnAnalysisResponse,
    TextExampleResponse,
    TextIntelligenceReportResponse,
    TextStatisticsResponse,
    TimePointResponse,
)

PREVIEW_NOTE = (
    "A bounded sample of the uploaded rows, shown to make the data recognisable. Values are "
    "truncated and email columns are hidden."
)


def column_to_response(profile: ColumnProfile) -> ColumnProfileResponse:
    return ColumnProfileResponse(
        index=profile.index,
        name=profile.name,
        technical_type=profile.technical_type.value,
        semantic_role=profile.semantic_role.value,
        role_confidence=profile.role_confidence,
        role_reason=profile.role_reason,
        analyzed_count=profile.analyzed_count,
        non_empty_count=profile.non_empty_count,
        null_count=profile.null_count,
        null_percentage=profile.null_percentage,
        unique_count=profile.unique_count,
        uniqueness_ratio=profile.uniqueness_ratio,
        sample_values=profile.sample_values,
        numeric=(NumericStatisticsResponse(**vars(profile.numeric)) if profile.numeric else None),
        categorical=(
            CategoricalStatisticsResponse(**vars(profile.categorical))
            if profile.categorical
            else None
        ),
        datetime_stats=(
            DatetimeStatisticsResponse(**vars(profile.datetime_stats))
            if profile.datetime_stats
            else None
        ),
        text=(TextStatisticsResponse(**vars(profile.text)) if profile.text else None),
        type_mismatch_count=profile.type_mismatch_count,
        type_mismatch_examples=profile.type_mismatch_examples,
        numeric_unit=profile.numeric_unit,
    )


def quality_to_response(report: QualityReport) -> QualityReportResponse:
    return QualityReportResponse(
        health_score=report.health_score,
        health_band=report.health_band,
        issues=[
            QualityIssueResponse(
                issue_type=issue.issue_type.value,
                severity=issue.severity.value,
                column=issue.column,
                title=issue.title,
                explanation=issue.explanation,
                recommendation=issue.recommendation,
                affected_count=issue.affected_count,
                affected_percentage=issue.affected_percentage,
                examples=issue.examples,
                score_penalty=issue.score_penalty,
            )
            for issue in report.issues
        ],
        counts_by_severity=report.counts_by_severity,
        total_cells=report.total_cells,
        missing_cells=report.missing_cells,
        missing_percentage=report.missing_percentage,
        duplicate_rows=report.duplicate_rows,
        duplicate_row_percentage=report.duplicate_row_percentage,
        scoring_rules=report.scoring_rules,
        missing_concentration=(
            MissingConcentrationResponse(**vars(report.missing_concentration))
            if report.missing_concentration
            else None
        ),
        checks=[QualityCheckResponse(**vars(check)) for check in report.checks],
        projected_health_score=report.projected_health_score,
        projected_health_band=report.projected_health_band,
        resolvable_penalty=report.resolvable_penalty,
        resolvable_issue_types=report.resolvable_issue_types,
    )


def cleaning_to_response(
    recommendations: list[CleaningRecommendation],
) -> list[CleaningRecommendationResponse]:
    return [
        CleaningRecommendationResponse(
            action=item.action.value,
            applicability=item.applicability.value,
            column=item.column,
            title=item.title,
            reason=item.reason,
            affected_data=item.affected_data,
            why=item.why,
            expected_impact=item.expected_impact,
            affected_count=item.affected_count,
            affected_percentage=item.affected_percentage,
            severity=item.severity.value,
            source_issue=item.source_issue.value,
            examples=item.examples,
        )
        for item in recommendations
    ]


def relationships_to_response(report: RelationshipReport) -> RelationshipReportResponse:
    return RelationshipReportResponse(
        analyzable=report.analyzable,
        unavailable_reason=report.unavailable_reason,
        correlation_columns=report.correlation_columns,
        correlation_matrix=report.correlation_matrix,
        strongest_positive=[
            CorrelationPairResponse(**vars(pair)) for pair in report.strongest_positive
        ],
        strongest_negative=[
            CorrelationPairResponse(**vars(pair)) for pair in report.strongest_negative
        ],
        group_differences=[
            GroupDifferenceResponse(**vars(difference)) for difference in report.group_differences
        ],
        excluded_columns=report.excluded_columns,
        coverage_note=report.coverage_note,
        disclaimer=report.disclaimer,
    )


def temporal_to_response(report: TemporalReport) -> TemporalReportResponse:
    return TemporalReportResponse(
        analyzable=report.analyzable,
        unavailable_reason=report.unavailable_reason,
        date_columns=report.date_columns,
        primary_date_column=report.primary_date_column,
        granularity=report.granularity,
        earliest=report.earliest,
        latest=report.latest,
        span_days=report.span_days,
        series=[TimePointResponse(**vars(point)) for point in report.series],
        volume_trend=(
            MetricTrendResponse(**vars(report.volume_trend)) if report.volume_trend else None
        ),
        metric_trends=[MetricTrendResponse(**vars(trend)) for trend in report.metric_trends],
        rows_without_date=report.rows_without_date,
        coverage_note=report.coverage_note,
    )


def text_to_response(report: TextIntelligenceReport) -> TextIntelligenceReportResponse:
    return TextIntelligenceReportResponse(
        analyzable=report.analyzable,
        unavailable_reason=report.unavailable_reason,
        columns=[
            TextColumnAnalysisResponse(
                column=column.column,
                analyzed_count=column.analyzed_count,
                total_non_empty=column.total_non_empty,
                sampled=column.sampled,
                coverage_percentage=column.coverage_percentage,
                average_length=column.average_length,
                language_distribution=column.language_distribution,
                sentiment_distribution=column.sentiment_distribution,
                dominant_sentiment=column.dominant_sentiment,
                positive_to_negative_ratio=column.positive_to_negative_ratio,
                positive_examples=[
                    TextExampleResponse(**vars(item)) for item in column.positive_examples
                ],
                negative_examples=[
                    TextExampleResponse(**vars(item)) for item in column.negative_examples
                ],
                complaints=[TextExampleResponse(**vars(item)) for item in column.complaints],
                requests=[TextExampleResponse(**vars(item)) for item in column.requests],
                themes=column.themes,
                unanalyzable_count=column.unanalyzable_count,
                spam_count=column.spam_count,
            )
            for column in report.columns
        ],
        skipped_columns=report.skipped_columns,
    )


def charts_to_response(charts: list[ChartSpec]) -> list[ChartSpecResponse]:
    return [
        ChartSpecResponse(
            chart_id=chart.chart_id,
            kind=chart.kind.value,
            section=chart.section.value,
            title=chart.title,
            subtitle=chart.subtitle,
            x_label=chart.x_label,
            y_label=chart.y_label,
            columns=chart.columns,
            data=chart.data,
            coverage_note=chart.coverage_note,
            meta=chart.meta,
        )
        for chart in charts
    ]


def insights_to_response(
    result: DatasetInsightResult, facts: list[DatasetFact]
) -> DatasetInsightsResponse:
    return DatasetInsightsResponse(
        insights=[DatasetInsightResponse(**vars(insight)) for insight in result.insights],
        executive_summary=ExecutiveSummaryResponse(**vars(result.executive_summary)),
        facts=[DatasetFactResponse(**vars(fact)) for fact in facts],
        generated_by=result.generated_by,
        provider_status=result.provider_status,
        provider_used=result.provider_used,
        model_used=result.model_used,
        prompt_version=result.prompt_version,
        unavailable_reason=result.unavailable_reason,
    )


def build_capabilities(analysis: EngineAnalysis) -> DatasetCapabilityAvailability:
    return DatasetCapabilityAvailability(
        has_quality_issues=bool(analysis.quality.issues),
        has_numeric_columns=any(profile.is_numeric_metric for profile in analysis.columns),
        has_relationships=(
            analysis.relationships.analyzable or bool(analysis.relationships.group_differences)
        ),
        has_temporal=analysis.temporal.analyzable,
        has_text=analysis.text.analyzable,
        has_ai_insights=bool(analysis.insights.insights),
    )


def analysis_to_persisted_fields(analysis: EngineAnalysis) -> dict:
    """The exact column values written to `dataset_analyses`.

    Every JSON section is produced by a pydantic model in `json` mode, so
    datetimes and enums are already primitives and the stored document is
    directly re-validatable by the same model on read.
    """
    overview = DatasetOverviewResponse(**vars(analysis.overview))
    coverage = DatasetCoverageResponse(**analysis.coverage)
    return {
        "schema_version": analysis.schema_version,
        "source_kind": analysis.overview.source_kind,
        "file_name": analysis.overview.file_name[:255],
        "file_type": analysis.overview.file_type[:16],
        "file_size_bytes": analysis.overview.file_size_bytes,
        "row_count": analysis.overview.row_count,
        "column_count": analysis.overview.column_count,
        "analyzed_row_count": analysis.coverage["analyzed_rows"],
        "health_score": analysis.quality.health_score,
        "missing_percentage": analysis.quality.missing_percentage,
        "duplicate_row_count": analysis.quality.duplicate_rows,
        "sheet_name": (
            analysis.overview.sheet_name[:255] if analysis.overview.sheet_name else None
        ),
        "insights_generated_by": analysis.insights.generated_by,
        "analysis_duration_ms": analysis.duration_ms,
        "overview_json": overview.model_dump(mode="json"),
        "coverage_json": coverage.model_dump(mode="json"),
        "columns_json": {
            "columns": [
                column_to_response(profile).model_dump(mode="json") for profile in analysis.columns
            ]
        },
        "quality_json": quality_to_response(analysis.quality).model_dump(mode="json"),
        "cleaning_json": {
            "recommendations": [
                item.model_dump(mode="json") for item in cleaning_to_response(analysis.cleaning)
            ]
        },
        "relationships_json": relationships_to_response(analysis.relationships).model_dump(
            mode="json"
        ),
        "temporal_json": temporal_to_response(analysis.temporal).model_dump(mode="json"),
        "text_json": text_to_response(analysis.text).model_dump(mode="json"),
        "charts_json": {
            "charts": [
                chart.model_dump(mode="json") for chart in charts_to_response(analysis.charts)
            ]
        },
        "insights_json": {
            **insights_to_response(analysis.insights, analysis.facts).model_dump(mode="json"),
            "capabilities": build_capabilities(analysis).model_dump(mode="json"),
        },
        "preview_json": DatasetPreviewResponse(
            columns=analysis.preview_columns,
            rows=analysis.preview_rows,
            note=PREVIEW_NOTE,
        ).model_dump(mode="json"),
    }
