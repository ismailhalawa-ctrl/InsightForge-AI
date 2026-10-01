from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import InsightProvider, QueryAnswerType, QueryMode, RecordType

_QUESTION_MAX_CHARS = 2000
_LANGUAGE_MAX_CHARS = 16
_SENTIMENT_MAX_CHARS = 16


class QueryFiltersRequest(BaseModel):
    record_type: RecordType | None = None
    language: str | None = Field(default=None, max_length=_LANGUAGE_MAX_CHARS)
    sentiment: str | None = Field(default=None, max_length=_SENTIMENT_MAX_CHARS)
    min_rating: float | None = Field(default=None, ge=0)
    max_rating: float | None = Field(default=None, ge=0)
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None


class AskDataRequest(BaseModel):
    question: str = Field(min_length=1, max_length=_QUESTION_MAX_CHARS)
    job_id: UUID | None = None
    dataset_id: UUID | None = None
    comparison_id: UUID | None = None
    action_plan_id: UUID | None = None
    filters: QueryFiltersRequest | None = None
    mode: QueryMode = QueryMode.auto


class EvidenceReferenceOut(BaseModel):
    evidence_id: UUID
    excerpt: str
    sentiment: str
    language: str


class SignalReferenceOut(BaseModel):
    signal_id: UUID
    title: str
    signal_type: str
    priority_score: float | None


class TrendReferenceOut(BaseModel):
    signal_trend_id: UUID
    title: str
    trend: str


class OutcomeReferenceOut(BaseModel):
    action_outcome_id: UUID
    outcome: str
    score: float | None


class AskDataResponse(BaseModel):
    answer: str
    answer_type: QueryAnswerType
    confidence: float
    limitations: list[str]
    evidence_references: list[EvidenceReferenceOut]
    signal_references: list[SignalReferenceOut]
    trend_references: list[TrendReferenceOut]
    outcome_references: list[OutcomeReferenceOut]
    record_count_considered: int
    filters_applied: dict[str, Any]
    provider: InsightProvider
    model_name: str | None
    generated_at: datetime
