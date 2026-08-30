"""Read API for a persisted dataset analysis.

Every endpoint here is a CACHE READ. The analysis was computed once, by the
worker, during the job; opening it from History, switching between result
pages or exporting it never recomputes anything and never touches the
uploaded file. That is what makes "leave the page, come back, see the same
results immediately" true rather than aspirational.

Sectioned to match the result pages, so a page loads what it renders and
nothing else. `/columns` is paginated because a 100-column upload has a
hundred full statistical profiles behind it, and the Explore page shows a
screenful at a time.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession
from app.api.deps_auth import CurrentUserDep
from app.datasets.insights import scrub_unsupported_sentences
from app.datasets.quality import canonicalize_health_band_text
from app.models.dataset_analysis import DatasetAnalysis
from app.repositories.analysis_job import AnalysisJobRepository
from app.repositories.dataset_analysis import DatasetAnalysisRepository
from app.schemas.dataset_intelligence import (
    ChartSpecResponse,
    CleaningRecommendationResponse,
    ColumnProfileResponse,
    DatasetAnalysisResponse,
    DatasetAnalysisSummaryResponse,
    DatasetCapabilityAvailability,
    DatasetColumnsResponse,
    DatasetCoverageResponse,
    DatasetInsightsResponse,
    DatasetOverviewResponse,
    DatasetPreviewResponse,
    DatasetQualityResponse,
    DatasetRelationshipsResponse,
    DatasetTextResponse,
    DatasetTrendsResponse,
    ExecutiveSummaryResponse,
    QualityReportResponse,
    RelationshipReportResponse,
    TemporalReportResponse,
    TextIntelligenceReportResponse,
)

router = APIRouter(prefix="/analysis/jobs", tags=["dataset-intelligence"])

_MAX_COLUMN_LIMIT = 100

_INSIGHT_TEXT_FIELDS = ("title", "explanation", "evidence", "impact", "recommended_action")
_SUMMARY_TEXT_FIELDS = ("scope", "data_health")
_SUMMARY_LIST_FIELDS = ("strongest_findings", "key_risks", "recommended_actions")

# Findings shown on the Overview. Deliberately fewer than the AI Insights
# page carries: the Overview answers "what should I care about", and a
# six-item list on a summary screen is a second AI Insights page.
_OVERVIEW_FINDING_COUNT = 3


def _load(db, current_user, job_id: UUID, summary_only: bool = False) -> DatasetAnalysis:
    """Ownership is checked against the JOB, never against the analysis row.

    A dataset_analyses row has no user_id of its own -- it belongs to the job
    that produced it, and that job's ownership is the one already enforced
    everywhere else. Checking the job means there is exactly one ownership
    rule in the product rather than a second one that could disagree.
    """
    job = AnalysisJobRepository(db).get_by_id(job_id)
    is_admin = current_user.role.value == "admin"
    if job is None or (not is_admin and job.user_id != current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")
    repository = DatasetAnalysisRepository(db)
    row = repository.get_summary(job_id) if summary_only else repository.get(job_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This analysis has no dataset intelligence result",
        )
    return row


def _measured_vocabulary(insights: dict) -> str:
    """What the stored analysis asserted, as the allow-list for the scrub."""
    parts: list[str] = []
    for fact in insights.get("facts", []) or []:
        if isinstance(fact, dict):
            parts.append(str(fact.get("statement", "")))
            parts.extend(str(column) for column in fact.get("columns", []) or [])
    return " ".join(parts).lower()


def _present(text, measured: str) -> str:
    """Corrects a stale band word and drops unmeasured sentences on read."""
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    return canonicalize_health_band_text(scrub_unsupported_sentences(text, measured))


def _sanitize_insight(insight: dict, measured: str) -> dict:
    if not isinstance(insight, dict):
        return insight
    cleaned = dict(insight)
    for field in _INSIGHT_TEXT_FIELDS:
        if isinstance(cleaned.get(field), str):
            cleaned[field] = _present(cleaned[field], measured)
    for field in ("title", "explanation", "impact"):
        if not cleaned.get(field):
            cleaned[field] = cleaned.get("evidence") or insight.get(field, "")
    if not cleaned.get("recommended_action"):
        cleaned["recommended_action"] = None
    return cleaned


def _sanitize_summary(summary: dict, measured: str) -> dict:
    if not isinstance(summary, dict):
        return summary
    cleaned = dict(summary)
    for field in _SUMMARY_TEXT_FIELDS:
        if isinstance(cleaned.get(field), str):
            cleaned[field] = _present(cleaned[field], measured)
    for field in _SUMMARY_LIST_FIELDS:
        values = cleaned.get(field)
        if isinstance(values, list):
            cleaned[field] = [
                text for text in (_present(item, measured) for item in values) if text
            ]
    return cleaned


def _charts_for(row: DatasetAnalysis, sections: set[str]) -> list[ChartSpecResponse]:
    return [
        ChartSpecResponse.model_validate(chart)
        for chart in (row.charts_json or {}).get("charts", [])
        if chart.get("section") in sections
    ]


def _summary(row: DatasetAnalysis) -> DatasetAnalysisSummaryResponse:
    return DatasetAnalysisSummaryResponse(
        job_id=str(row.job_id),
        dataset_id=str(row.dataset_id) if row.dataset_id else None,
        schema_version=row.schema_version,
        source_kind=row.source_kind,
        file_name=row.file_name,
        file_type=row.file_type,
        file_size_bytes=row.file_size_bytes,
        row_count=row.row_count,
        column_count=row.column_count,
        analyzed_row_count=row.analyzed_row_count,
        health_score=row.health_score,
        missing_percentage=row.missing_percentage,
        duplicate_row_count=row.duplicate_row_count,
        sheet_name=row.sheet_name,
        insights_generated_by=row.insights_generated_by,
        analysis_duration_ms=row.analysis_duration_ms,
        created_at=row.created_at,
    )


@router.get(
    "/{job_id}/dataset",
    response_model=DatasetAnalysisResponse,
    summary="Overview of a persisted dataset analysis",
    description=(
        "A pure cache read of the analysis the worker computed during the job. "
        "Column profiles, the correlation matrix and the full chart set are served by the "
        "section endpoints, so this stays an Overview-sized payload."
    ),
)
async def get_dataset_analysis(
    job_id: UUID, db: DbSession, current_user: CurrentUserDep
) -> DatasetAnalysisResponse:
    row = _load(db, current_user, job_id)
    insights = row.insights_json or {}
    quality = row.quality_json or {}
    measured = _measured_vocabulary(insights)
    return DatasetAnalysisResponse(
        summary=_summary(row),
        overview=DatasetOverviewResponse.model_validate(row.overview_json),
        coverage=DatasetCoverageResponse.model_validate(row.coverage_json),
        quality_summary={
            "health_score": quality.get("health_score", 0),
            "health_band": quality.get("health_band", "unknown"),
            "counts_by_severity": quality.get("counts_by_severity", {}),
            "issue_count": len(quality.get("issues", [])),
            "missing_percentage": quality.get("missing_percentage", 0.0),
            "duplicate_rows": quality.get("duplicate_rows", 0),
            "missing_concentration": quality.get("missing_concentration"),
            "projected_health_score": quality.get("projected_health_score"),
            "projected_health_band": quality.get("projected_health_band"),
        },
        executive_summary=ExecutiveSummaryResponse.model_validate(
            _sanitize_summary(insights.get("executive_summary", {}) or {}, measured)
        ),
        strongest_findings=[
            _sanitize_insight(finding, measured)
            for finding in insights.get("insights", [])[:_OVERVIEW_FINDING_COUNT]
        ],
        capabilities=DatasetCapabilityAvailability.model_validate(
            insights.get(
                "capabilities",
                {
                    "has_quality_issues": False,
                    "has_numeric_columns": False,
                    "has_relationships": False,
                    "has_temporal": False,
                    "has_text": False,
                    "has_ai_insights": False,
                },
            )
        ),
        charts=_charts_for(row, {"overview", "quality"}),
    )


@router.get(
    "/{job_id}/dataset/columns",
    response_model=DatasetColumnsResponse,
    summary="Paginated column profiles for a dataset analysis",
)
async def get_dataset_columns(
    job_id: UUID,
    db: DbSession,
    current_user: CurrentUserDep,
    limit: int = Query(default=25, ge=1, le=_MAX_COLUMN_LIMIT),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=255),
) -> DatasetColumnsResponse:
    row = _load(db, current_user, job_id)
    columns = (row.columns_json or {}).get("columns", [])
    if search:
        needle = search.strip().lower()
        columns = [
            column
            for column in columns
            if needle in str(column.get("name", "")).lower()
            or needle in str(column.get("semantic_role", "")).lower()
            or needle in str(column.get("technical_type", "")).lower()
        ]
    window = columns[offset : offset + limit]
    return DatasetColumnsResponse(
        columns=[ColumnProfileResponse.model_validate(column) for column in window],
        total=len(columns),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{job_id}/dataset/quality",
    response_model=DatasetQualityResponse,
    summary="Data quality report and cleaning recommendations",
)
async def get_dataset_quality(
    job_id: UUID, db: DbSession, current_user: CurrentUserDep
) -> DatasetQualityResponse:
    row = _load(db, current_user, job_id)
    return DatasetQualityResponse(
        quality=QualityReportResponse.model_validate(row.quality_json),
        cleaning=[
            CleaningRecommendationResponse.model_validate(item)
            for item in (row.cleaning_json or {}).get("recommendations", [])
        ],
        charts=_charts_for(row, {"quality"}),
    )


@router.get(
    "/{job_id}/dataset/relationships",
    response_model=DatasetRelationshipsResponse,
    summary="Correlations and group differences",
)
async def get_dataset_relationships(
    job_id: UUID, db: DbSession, current_user: CurrentUserDep
) -> DatasetRelationshipsResponse:
    row = _load(db, current_user, job_id)
    return DatasetRelationshipsResponse(
        relationships=RelationshipReportResponse.model_validate(row.relationships_json),
        charts=_charts_for(row, {"relationships"}),
    )


@router.get(
    "/{job_id}/dataset/trends",
    response_model=DatasetTrendsResponse,
    summary="Temporal analysis, or a truthful statement that there is none",
)
async def get_dataset_trends(
    job_id: UUID, db: DbSession, current_user: CurrentUserDep
) -> DatasetTrendsResponse:
    row = _load(db, current_user, job_id)
    return DatasetTrendsResponse(
        temporal=TemporalReportResponse.model_validate(row.temporal_json),
        charts=_charts_for(row, {"trends"}),
    )


@router.get(
    "/{job_id}/dataset/text",
    response_model=DatasetTextResponse,
    summary="Per-column text intelligence for the dataset's free-text columns",
)
async def get_dataset_text(
    job_id: UUID, db: DbSession, current_user: CurrentUserDep
) -> DatasetTextResponse:
    row = _load(db, current_user, job_id)
    return DatasetTextResponse(text=TextIntelligenceReportResponse.model_validate(row.text_json))


@router.get(
    "/{job_id}/dataset/insights",
    response_model=DatasetInsightsResponse,
    summary="Evidence-grounded insights and the facts they cite",
)
async def get_dataset_insights(
    job_id: UUID, db: DbSession, current_user: CurrentUserDep
) -> DatasetInsightsResponse:
    row = _load(db, current_user, job_id)
    payload = dict(row.insights_json or {})
    measured = _measured_vocabulary(payload)
    payload["insights"] = [
        _sanitize_insight(insight, measured) for insight in payload.get("insights", []) or []
    ]
    if isinstance(payload.get("executive_summary"), dict):
        payload["executive_summary"] = _sanitize_summary(payload["executive_summary"], measured)
    return DatasetInsightsResponse.model_validate(payload)


@router.get(
    "/{job_id}/dataset/preview",
    response_model=DatasetPreviewResponse,
    summary="A bounded, sanitized sample of the uploaded rows",
)
async def get_dataset_preview(
    job_id: UUID, db: DbSession, current_user: CurrentUserDep
) -> DatasetPreviewResponse:
    row = _load(db, current_user, job_id)
    return DatasetPreviewResponse.model_validate(row.preview_json)
