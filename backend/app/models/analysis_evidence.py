import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import RecordType, SourceType

# Real JSONB on PostgreSQL; plain JSON on any other dialect (SQLite in fast
# offline unit tests) -- same cross-dialect pattern used for AnalysisJob.
_JSONVariant = JSON().with_variant(JSONB(), "postgresql")

# Evidence stores bounded, sanitized text EXCERPTS, not full duplicates or a
# hard reference to a source-specific table -- see AnalysisRecordEvidence
# docstring for the reasoning.
EVIDENCE_TEXT_EXCERPT_MAX_CHARS = 500


class AnalysisRecordEvidence(Base):
    """Persisted, source-agnostic per-record evidence for insight generation.

    Written once, after Text Intelligence + sentiment fusion complete for a
    record, by AnalysisJobRunner. Insight generation reads only from this
    table (plus AnalysisJob itself) -- it never re-collects from the source,
    never reruns the transformer sentiment models, and never reruns Text
    Intelligence, and it never needs a still-running worker process.

    Table/column naming (Sprint 15): the table name `analysis_comment_evidence`
    and the `like_count`/`published_at` columns are kept for Sprint <=14.1
    compatibility rather than renamed -- this is the "retain table/model
    while making semantics generic" strategy. `record_type`, `source_record_id`,
    `engagement`, and `occurred_at` are the new generic-facing columns;
    `like_count`/`published_at` remain populated for comment records so
    nothing that already reads them breaks.

    Text storage decision: `text_excerpt` and `processed_text_excerpt` store
    bounded (EVIDENCE_TEXT_EXCERPT_MAX_CHARS) sanitized excerpts directly on
    the row -- not a full duplicate of the original record, and not a hard
    foreign key to a source-specific cache table. This keeps the model
    genuinely source-agnostic (a future non-YouTube source populates the
    same columns without needing its own join) while still being practical
    and deterministic: insight generation (keyword extraction, embeddings,
    short quoted evidence in reports) needs a preview of the text, not
    necessarily every character of an unbounded record. The authoritative
    full original text is available via SourceRecord.original_text
    (source_record_id) when persisted there; evidence itself never depends
    on that join to function.
    """

    __tablename__ = "analysis_comment_evidence"
    __table_args__ = (
        UniqueConstraint("job_id", "source_key", name="uq_evidence_job_source_key"),
        Index("ix_evidence_job_id", "job_id"),
        Index("ix_evidence_job_sentiment", "job_id", "sentiment"),
        Index("ix_evidence_job_is_spam", "job_id", "is_spam"),
        Index("ix_evidence_job_clean_analysis", "job_id", "included_in_clean_analysis"),
        Index("ix_evidence_job_source_position", "job_id", "source_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE")
    )

    source_key: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False, length=32, validate_strings=True)
    )
    source_external_id: Mapped[str] = mapped_column(String(64))
    source_position: Mapped[int] = mapped_column(Integer)

    text_excerpt: Mapped[str] = mapped_column(String(EVIDENCE_TEXT_EXCERPT_MAX_CHARS))
    processed_text_excerpt: Mapped[str] = mapped_column(String(EVIDENCE_TEXT_EXCERPT_MAX_CHARS))
    language: Mapped[str] = mapped_column(String(16))
    routing_category: Mapped[str] = mapped_column(String(16))

    sentiment: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    processable: Mapped[bool] = mapped_column(Boolean)
    analyzed: Mapped[bool] = mapped_column(Boolean)
    uncertainty_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Reproducibility metadata (Sprint 31): which model actually produced
    # this result, and which pipeline-config version was active. Nullable --
    # null for rows written before this column existed, and for rows where
    # no model ran at all (trivial/unsupported/emoji-only-resolved). Never
    # read by scoring/routing/aggregation logic, evidence only.
    model_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Prediction margin (Sprint 32): second-highest class confidence and the
    # top1-top2 margin. Null when no model ran.
    second_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_margin: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Arabic fallback cascade audit trail (Sprint 32). All null/False for
    # every row while the cascade stays disabled (the default). When
    # cascade_triggered, cascade_primary_confidence/cascade_primary_margin
    # and cascade_fallback_confidence preserve each model's own numbers
    # (regardless of which one produced the final sentiment above) so
    # cascade accuracy can be measured after the fact.
    cascade_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    cascade_model_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cascade_primary_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    cascade_primary_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    cascade_fallback_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    cascade_labels_disagreed: Mapped[bool] = mapped_column(Boolean, default=False)

    # LLM escalation audit trail (Sprint 33). sentiment/confidence above are
    # always the FINAL decision; fast_sentiment/fast_confidence preserve the
    # unmodified FAST (Sprint <=32) result even when the LLM replaced it.
    # All null/False for sentiment_mode="fast" jobs and for any item the LLM
    # never actually ran on.
    sentiment_mode: Mapped[str] = mapped_column(String(16), default="fast", server_default="fast")
    fast_sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fast_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    llm_fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_degraded: Mapped[bool] = mapped_column(Boolean, default=False)

    is_spam: Mapped[bool] = mapped_column(Boolean, default=False)
    spam_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_sarcasm: Mapped[bool] = mapped_column(Boolean, default=False)
    sarcasm_score: Mapped[int] = mapped_column(Integer, default=0)

    intents: Mapped[list] = mapped_column(_JSONVariant, default=list)
    targets: Mapped[list] = mapped_column(_JSONVariant, default=list)
    lexical_data: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    emoji_data: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    escalation_reasons: Mapped[list] = mapped_column(_JSONVariant, default=list)

    duplicate_signature: Mapped[str] = mapped_column(String(64), default="")
    duplicate_group_size: Mapped[int] = mapped_column(Integer, default=1)

    like_count: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    record_type: Mapped[RecordType] = mapped_column(
        Enum(RecordType, native_enum=False, length=32, validate_strings=True),
        default=RecordType.comment,
    )
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True
    )
    engagement: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    included_in_clean_analysis: Mapped[bool] = mapped_column(Boolean, default=False)

    # Phase 3: this record is REFERENCE material (repository documentation),
    # not somebody's opinion.
    #
    # Reference rows are deliberately written with
    # included_in_clean_analysis=False, which is what keeps them out of every
    # existing feedback consumer -- sentiment timelines, engagement scatter,
    # windowed counts, complaint/praise extraction, AI insight evidence --
    # without editing any of those queries. This column then lets the one
    # consumer that SHOULD see documentation opt back in: semantic retrieval
    # (app/services/assistant/rag.py), so the Assistant can ground an answer
    # in a README while the sentiment percentages stay a measure of what
    # people actually said.
    #
    # Source-agnostic and defaulted False, so every pre-Phase-3 row is
    # correct as it stands with no backfill.
    is_reference_content: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )

    # Bounded, source-agnostic grounding metadata projected from the source
    # record (Phase 2). NOT a copy of SourceRecord.record_metadata -- a strict
    # allow-list, size-bounded and priority-ordered, so the evidence schema
    # cannot be widened by a connector and a single pathological field cannot
    # push out the identity fields. See
    # app/services/analysis_job/evidence_metadata.py for what survives and why.
    #
    # This is what lets a reader answer "which exact source item produced this
    # evidence?" and link back to it: before Phase 2 the runner dropped
    # record_metadata entirely at this boundary, so every structural fact --
    # repository, issue number, labels, file path, canonical URL -- was lost
    # at precisely the layer RAG, the Assistant, insights and reports read
    # from.
    #
    # Nullable with no backfill: every pre-Phase-2 row reads as None, which is
    # the same "no grounding metadata available" case a source that supplies
    # none produces, so there is only ever one absent-representation to
    # handle. Re-running an analysis produces enriched rows.
    source_metadata: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)

    # Cached semantic-search embedding for the Global AI Assistant's RAG
    # retrieval (app/services/assistant/rag.py) -- computed lazily (on first
    # retrieval touching this job, never during the analysis pipeline
    # itself) and persisted permanently so the same evidence is never
    # re-embedded across turns/sessions. Null until computed. A plain JSON
    # float list (not pgvector) is deliberate: per-job evidence volumes are
    # small enough (hundreds-low thousands of rows) that an in-process numpy
    # cosine ranking over cached vectors is simpler and dependency-free
    # compared to introducing a dedicated vector extension/service, while
    # remaining genuinely semantic (not ILIKE) -- see rag.py's module
    # docstring for the full tradeoff.
    embedding: Mapped[list | None] = mapped_column(_JSONVariant, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
