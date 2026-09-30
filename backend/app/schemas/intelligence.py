"""API contracts for the Product Intelligence layer.

Most responses ARE the service models (the document, the comparison, the
library page, the snapshot) -- they are user-safe by construction (see
services/intelligence) and re-declaring them here would only create a
second copy that could drift. This module holds the request shapes and the
few envelopes the routes add on top.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.intelligence.compare import AIComparison, ComparisonResult
from app.services.intelligence.contracts import AnalysisDocument, AnalysisQuality, DocumentSummary
from app.services.intelligence.library import LibraryItem, LibraryResponse, LibraryStats
from app.services.intelligence.recommendations import (
    RecommendationTrackingResponse,
    TrackedRecommendation,
)
from app.services.intelligence.workspace import WorkspaceSnapshot

ExportFormat = Literal["full_pdf", "executive_pdf", "json"]


class CompareAIRequest(BaseModel):
    a: UUID
    b: UUID
    language: Literal["en", "ar"] = "en"


class CompareCandidate(BaseModel):
    job_id: UUID
    title: str
    source_label: str
    kind: str
    created_at: str
    same_entity: bool
    quality_label: str | None = None
    finding_count: int = 0


class CompareCandidatesResponse(BaseModel):
    job_id: UUID
    candidates: list[CompareCandidate]


class ExportOption(BaseModel):
    format: str
    label: str
    description: str
    content_type: str
    available: bool = True
    # For the pre-existing formats that live on other endpoints.
    href: str | None = None
    kind: Literal["intelligence", "report", "records"] = "intelligence"


class ExportOptionsResponse(BaseModel):
    job_id: UUID
    options: list[ExportOption]


class RecommendationStatusRequest(BaseModel):
    status: Literal["open", "in_progress", "addressed"]


class AnalysisQualityResponse(BaseModel):
    job_id: UUID
    kind: str
    quality: AnalysisQuality
    finding_count: int
    strength_count: int
    worst_severity: str | None = None
    key_finding: str | None = None


__all__ = [
    "AIComparison",
    "AnalysisDocument",
    "AnalysisQualityResponse",
    "CompareAIRequest",
    "CompareCandidate",
    "CompareCandidatesResponse",
    "ComparisonResult",
    "DocumentSummary",
    "ExportFormat",
    "ExportOption",
    "ExportOptionsResponse",
    "LibraryItem",
    "LibraryResponse",
    "LibraryStats",
    "RecommendationStatusRequest",
    "RecommendationTrackingResponse",
    "TrackedRecommendation",
    "WorkspaceSnapshot",
]

_ = Field
