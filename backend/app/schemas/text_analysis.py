"""The wire shape of a persisted Pasted Text Intelligence analysis.

Every model here mirrors one JSON section of the `text_analyses` row, so a
response is a projection of stored data rather than something recomputed per
request. `state` travels with every measurement for the reason it exists at
all: a reader (and the Assistant) must be able to tell a counted zero from
an unavailable one.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

EvidenceStateName = Literal["measured", "detected", "inferred", "unavailable", "unverifiable"]
CoverageStatusName = Literal[
    "measured", "detected", "partial", "not_applicable", "unavailable", "not_performed"
]
SeverityName = Literal["high", "medium", "low", "info"]
FindingKindName = Literal["issue", "strength"]
AIStatusName = Literal["generated", "degraded", "unavailable", "disabled"]
AIGeneratedByName = Literal["ai", "deterministic"]
SentimentName = Literal["positive", "negative", "neutral", "mixed", "not_applicable"]


class TextMetricResponse(BaseModel):
    metric_id: str
    label: str
    value: int | float | str | bool | None = None
    unit: str = "count"
    state: EvidenceStateName = "measured"
    detail: str | None = None


class TextRatioResponse(BaseModel):
    ratio_id: str
    label: str
    numerator: int
    denominator: int
    value: float | None = None
    applicable: bool = True
    detail: str | None = None


class TextFindingResponse(BaseModel):
    finding_id: str
    rule_id: str
    domain: str
    kind: FindingKindName
    title: str
    description: str
    severity: SeverityName
    state: EvidenceStateName
    evidence_ids: list[str] = []
    recommendation: str | None = None


class TextEvidenceItemResponse(BaseModel):
    evidence_id: str
    category: str
    label: str
    value: str | None = None
    state: EvidenceStateName
    detail: str | None = None
    location: str | None = None


class TextCoverageAreaResponse(BaseModel):
    area: str
    label: str
    status: CoverageStatusName
    detail: str


class TextLanguageResponse(BaseModel):
    detected: str
    confidence: float | None = None
    state: EvidenceStateName
    mixed: bool = False
    arabic_word_count: int = 0
    latin_word_count: int = 0
    other_word_count: int = 0
    detail: str = ""


class TextMetricsResponse(BaseModel):
    character_count: int = 0
    character_count_no_spaces: int = 0
    word_count: int = 0
    unique_word_count: int = 0
    sentence_count: int = 0
    longest_sentence_words: int | None = None
    shortest_sentence_words: int | None = None
    average_words_per_sentence: float | None = None
    average_sentence_characters: float | None = None
    average_word_length: float | None = None
    lexical_diversity: float | None = None
    question_count: int = 0
    exclamation_count: int = 0
    number_count: int = 0
    url_count: int = 0
    email_count: int = 0


class TextBlockResponse(BaseModel):
    index: int
    text: str
    word_count: int
    character_count: int
    sentence_count: int
    kind: str


class TextRepetitionResponse(BaseModel):
    duplicate_paragraph_count: int = 0
    duplicate_sentence_count: int = 0
    most_repeated_excerpt: str | None = None
    most_repeated_count: int = 0


class TextStructureResponse(BaseModel):
    paragraph_count: int = 0
    non_empty_paragraph_count: int = 0
    heading_count: int = 0
    bullet_count: int = 0
    numbered_count: int = 0
    quote_count: int = 0
    code_block_count: int = 0
    list_block_count: int = 0
    shortest_paragraph_words: int | None = None
    longest_paragraph_words: int | None = None
    has_markdown_markers: bool = False
    headings: list[str] = []
    blocks: list[TextBlockResponse] = []
    repetition: TextRepetitionResponse = TextRepetitionResponse()


class TextAnalysisSummaryResponse(BaseModel):
    job_id: UUID
    dataset_id: UUID | None = None
    schema_version: int = 1
    title: str | None = None
    language: str | None = None
    language_state: str = "detected"
    language_mixed: bool = False
    word_count: int = 0
    character_count: int = 0
    sentence_count: int = 0
    paragraph_count: int = 0
    heading_count: int = 0
    unique_word_count: int = 0
    truncated: bool = False
    analysis_duration_ms: float = 0.0
    finding_count: int = 0
    strength_count: int = 0
    high_finding_count: int = 0
    medium_finding_count: int = 0
    low_finding_count: int = 0
    ai_status: AIStatusName | None = None
    ai_generated_by: AIGeneratedByName | None = None
    ai_topic_count: int = 0
    ai_insight_count: int = 0
    ai_recommendation_count: int = 0
    ai_sentiment: SentimentName | None = None
    created_at: datetime | None = None


class TextOverviewResponse(BaseModel):
    job_id: UUID
    summary: TextAnalysisSummaryResponse
    excerpt: str = ""
    truncated: bool = False
    original_character_count: int = 0
    analysed_character_count: int = 0
    metrics: TextMetricsResponse = TextMetricsResponse()
    language: TextLanguageResponse
    structure: TextStructureResponse = TextStructureResponse()
    domains: dict[str, list[TextMetricResponse]] = {}
    ratios: list[TextRatioResponse] = []
    coverage: list[TextCoverageAreaResponse] = []
    coverage_notes: list[str] = []


class TextFindingsResponse(BaseModel):
    job_id: UUID
    findings: list[TextFindingResponse] = []
    strengths: list[TextFindingResponse] = []
    severity_counts: dict[str, int] = {}


class TextEvidenceResponse(BaseModel):
    job_id: UUID
    items: list[TextEvidenceItemResponse] = []


# --- AI ---------------------------------------------------------------------


class TextAISummaryResponse(BaseModel):
    executive_summary: str = ""
    document_kind: str = ""
    key_points: list[str] = []
    takeaways: list[str] = []
    overall_stance: str = "mixed"


class TextAITopicResponse(BaseModel):
    topic_id: str
    label: str
    kind: Literal["explicit", "inferred"] = "inferred"
    prominence: Literal["high", "medium", "low"] = "medium"
    detail: str = ""
    evidence_ids: list[str] = []
    quote: str | None = None


class TextAIInsightResponse(BaseModel):
    insight_id: str
    category: str
    title: str
    finding: str = ""
    why_it_matters: str = ""
    claim_type: str = "reasoned_observation"
    confidence: Literal["high", "medium", "low"] = "medium"
    evidence_ids: list[str] = []
    quote: str | None = None


class TextAIRecommendationResponse(BaseModel):
    recommendation_id: str
    title: str
    action: str = ""
    basis: str = ""
    priority: Literal["high", "medium", "low"] = "medium"
    confidence: Literal["high", "medium", "low"] = "medium"
    evidence_ids: list[str] = []


class TextAISentimentResponse(BaseModel):
    label: SentimentName = "not_applicable"
    confidence: Literal["high", "medium", "low"] = "low"
    detail: str = ""
    evidence_ids: list[str] = []


class TextAIToneResponse(BaseModel):
    labels: list[str] = []
    detail: str = ""
    evidence_ids: list[str] = []


class TextAIGroundingRejectionResponse(BaseModel):
    rule: str
    detail: str
    location: str
    quote: str | None = None


class TextAIGroundingResponse(BaseModel):
    passed: bool = True
    repair_attempts: int = 0
    dropped_items: int = 0
    rejection_rules: list[str] = []
    rejections: list[TextAIGroundingRejectionResponse] = []


class TextAIResponse(BaseModel):
    job_id: UUID
    schema_version: int = 1
    status: AIStatusName = "unavailable"
    generated_by: AIGeneratedByName = "deterministic"
    provider_used: str | None = None
    model_used: str | None = None
    prompt_version: str = ""
    unavailable_reason: str | None = None
    duration_ms: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    summary: TextAISummaryResponse | None = None
    topics: list[TextAITopicResponse] = []
    insights: list[TextAIInsightResponse] = []
    recommendations: list[TextAIRecommendationResponse] = []
    sentiment: TextAISentimentResponse | None = None
    tone: TextAIToneResponse | None = None
    limitations: list[str] = []
    grounding: TextAIGroundingResponse | None = None


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}
