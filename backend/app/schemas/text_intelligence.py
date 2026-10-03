from typing import Literal

from pydantic import BaseModel

from app.schemas.sentiment import ModelRole, SentimentLabel

Polarity = Literal["positive", "negative"]
Strength = Literal["weak", "moderate", "strong"]

UnsupportedReason = Literal[
    "empty_text",
    "punctuation_only",
    "number_only",
    "url_only",
    "mention_only",
    "hashtag_only",
    "emoji_only_ambiguous",
    "unsupported_language",
    "unknown_language",
    "trivial_short_text",
    "processing_failure",
    "spam_excluded",
    "other",
]

SpamReason = Literal[
    "multiple_links",
    "suspicious_short_link",
    "whatsapp_contact",
    "phone_number",
    "promotional_cta",
    "strong_spam_keyword",
    "weak_spam_keywords",
    "excessive_emoji",
    "repeated_characters",
    "low_unique_word_ratio",
    "excessive_caps",
    "url_only",
    "mention_only",
    "hashtag_only",
    "duplicate_content",
    "self_promotion",
]

IntentCategory = Literal[
    "opinion",
    "question",
    "request",
    "suggestion",
    "complaint",
    "praise",
    "criticism",
    "disagreement",
    "discussion",
    "confusion",
    "support",
    "prayer",
    "other",
]

TargetCategory = Literal[
    "content",
    "explanation",
    "audio",
    "video_quality",
    "editing",
    "presenter",
    "code_examples",
    "pacing",
    "subtitles",
    "thumbnail_title",
    "product_service",
    "personal_life",
    "other",
    "unknown",
]

EscalationReason = Literal[
    "low_confidence",
    "low_margin",
    "model_rule_disagreement",
    "model_cascade_disagreement",
    "sarcasm",
    "mixed_language",
    "arabizi",
    "emoji_conflict",
    "complex_contrast",
    "ambiguous_target",
    "native_neutral",
    "protected_intent",
]


class EmojiSignal(BaseModel):
    total_emoji_count: int = 0
    positive_emoji_count: int = 0
    negative_emoji_count: int = 0
    ambiguous_emoji_count: int = 0
    sarcasm_emoji_count: int = 0
    unique_emojis: list[str] = []
    top_emojis: list[str] = []
    emoji_counts: dict[str, int] = {}
    is_emoji_only: bool = False


class LexicalMatch(BaseModel):
    polarity: Polarity
    strength: Strength
    category: str
    pattern_id: str
    language: Literal["ar", "en"]
    dialect: str | None = None
    negated: bool = False
    span: tuple[int, int] | None = None


class NegationEvidence(BaseModel):
    marker: str
    affected_text: str
    flipped: bool


class ContrastSpan(BaseModel):
    text: str
    polarity: Polarity | None = None
    strength: Strength | None = None
    is_post_connector: bool = False


class SpamSignal(BaseModel):
    is_spam: bool = False
    spam_reason: SpamReason | None = None
    matched_spam_rules: list[SpamReason] = []
    matched_rule_count: int = 0


class SarcasmSignal(BaseModel):
    is_sarcasm: bool = False
    sarcasm_score: int = 0
    matched_sarcasm_signals: list[str] = []


class ArabiziSignal(BaseModel):
    is_arabizi: bool = False
    arabizi_tokens: list[str] = []


class IntentSignal(BaseModel):
    primary_intent: IntentCategory = "other"
    intents: list[IntentCategory] = []
    intent_evidence: list[str] = []


class TargetSignal(BaseModel):
    target_scope: TargetCategory = "unknown"
    target_evidence: list[str] = []


class GreetingSignal(BaseModel):
    is_greeting: bool = False
    matched: list[str] = []


class OffTopicSignal(BaseModel):
    is_off_topic: bool = False
    matched: list[str] = []


class EmotionSignal(BaseModel):
    is_emotion_only: bool = False
    matched: list[str] = []


class AnticipationSignal(BaseModel):
    is_anticipation: bool = False
    matched: list[str] = []


class TextIntelligenceResult(BaseModel):
    source_key: str | None = None
    original_text: str
    processed_text: str
    detected_language: str
    routing_category: str
    processing_failed: bool = False
    processable: bool
    trivial: bool = False
    trivial_reason: UnsupportedReason | None = None

    is_arabizi: bool = False
    arabizi_tokens: list[str] = []

    emoji_signal: EmojiSignal = EmojiSignal()
    spam: SpamSignal = SpamSignal()
    sarcasm: SarcasmSignal = SarcasmSignal()
    intent: IntentSignal = IntentSignal()
    target: TargetSignal = TargetSignal()
    greeting: GreetingSignal = GreetingSignal()
    off_topic: OffTopicSignal = OffTopicSignal()
    emotion: EmotionSignal = EmotionSignal()
    anticipation: AnticipationSignal = AnticipationSignal()

    lexical_polarity: Polarity | None = None
    lexical_strength: Strength | None = None
    lexical_matches: list[LexicalMatch] = []

    negation_detected: bool = False
    negation_evidence: list[NegationEvidence] = []

    contrast_detected: bool = False
    contrast_spans: list[ContrastSpan] = []

    duplicate_signature: str = ""
    duplicate_of_index: int | None = None

    model_sentiment: SentimentLabel | None = None
    model_confidence: float | None = None
    # Prediction margin (Sprint 32) -- see SentimentResult for definitions.
    model_second_confidence: float | None = None
    model_confidence_margin: float | None = None
    # Arabic fallback cascade (Sprint 32) -- see SentimentResult for
    # definitions. False/None for every item while the cascade is disabled.
    cascade_triggered: bool = False
    cascade_model_role: ModelRole | None = None
    cascade_primary_confidence: float | None = None
    cascade_primary_margin: float | None = None
    cascade_fallback_confidence: float | None = None
    cascade_labels_disagreed: bool = False
    # Identity of the model that actually produced model_sentiment/
    # model_confidence -- None when no model ran (trivial/unsupported/
    # emoji-only-resolved items). Reproducibility metadata only; never used
    # in scoring or routing decisions.
    model_name: str | None = None
    model_revision: str | None = None
    model_role: ModelRole | None = None
    # Version of the preprocessing/routing/fusion pipeline that produced
    # this result -- see TEXT_INTELLIGENCE_PIPELINE_VERSION. The default
    # below MUST match that constant (a test enforces this); it exists only
    # so pre-Sprint-31 test fixtures that construct this model directly
    # don't all need updating -- the real service always passes it
    # explicitly.
    pipeline_version: str = "4"

    sentiment: SentimentLabel
    confidence: float | None = None
    analyzed: bool = False

    # LLM escalation (Sprint 33). sentiment/confidence above are always the
    # FINAL decision (FAST, unless the LLM result passed the final-decision
    # gate). fast_sentiment/fast_confidence preserve the original FAST
    # (Sprint <=32 pipeline) result even when the LLM replaced it, so both
    # are auditable. All None/False for FAST-mode jobs and for any item the
    # LLM never actually ran on.
    sentiment_mode: str = "fast"
    fast_sentiment: SentimentLabel | None = None
    fast_confidence: float | None = None
    llm_sentiment: SentimentLabel | None = None
    llm_confidence: float | None = None
    llm_reason: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    # True when this item was eligible/escalated but the LLM result was
    # missing/malformed/disallowed/below threshold, so FAST was kept.
    llm_fallback_used: bool = False
    # True when the whole batch/provider call failed and every item in it
    # fell back to FAST together (a stronger signal than a single item's
    # fallback -- see SentimentLLMService).
    llm_degraded: bool = False
    # True when the LLM disagreed but was NOT allowed to overwrite, because
    # the specialized classifier was already confident. The LLM's opinion is
    # still recorded in llm_sentiment for audit; this flag is what makes the
    # decision reviewable rather than invisible.
    llm_override_blocked: bool = False

    unsupported_reason: UnsupportedReason | None = None
    uncertainty_reason: str | None = None

    correction_reason: str | None = None
    correction_evidence: list[str] = []

    escalation_recommended: bool = False
    escalation_reasons: list[EscalationReason] = []

    evidence: list[str] = []
