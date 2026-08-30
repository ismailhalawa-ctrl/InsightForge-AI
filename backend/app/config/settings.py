import secrets
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MIN_AUTH_SECRET_LENGTH = 32
_SAFE_IMPORT_TEXT_ENCODINGS = frozenset({"utf-8", "utf-8-sig", "utf-16", "ascii"})

# Each entry pairs a secret field with the flag that records whether it was
# auto-generated (dev-only convenience) rather than explicitly configured.
# Used by _validate_secret_separation to compare only explicitly-supplied
# values -- two independently auto-generated secrets are vanishingly unlikely
# to collide and must never be flagged as a misconfiguration.
_SECRET_SEPARATION_FIELDS = (
    ("AUTH_ACCESS_TOKEN_SECRET", "AUTH_ACCESS_TOKEN_SECRET_AUTO_GENERATED"),
    ("AUTH_REFRESH_TOKEN_PEPPER", "AUTH_REFRESH_TOKEN_PEPPER_AUTO_GENERATED"),
    ("AUTH_SECURITY_TOKEN_PEPPER", "AUTH_SECURITY_TOKEN_PEPPER_AUTO_GENERATED"),
    ("RATE_LIMIT_IDENTITY_PEPPER", "RATE_LIMIT_IDENTITY_PEPPER_AUTO_GENERATED"),
    ("AUTH_SESSION_FINGERPRINT_PEPPER", "AUTH_SESSION_FINGERPRINT_PEPPER_AUTO_GENERATED"),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "InsightForge AI"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"

    DATABASE_URL: str = "postgresql://insightforge:changeme@db:5432/insightforge"
    # Dedicated database for the PostgreSQL integration test suite
    # (tests/integration/**/*_postgres.py). Those tests DELETE real rows
    # (users, analysis_jobs, refresh_sessions, ...) as part of their
    # cleanup -- they must never run against the same database a developer's
    # `docker compose up` backend is actually serving from. Left blank, it
    # defaults (see _default_test_database_url below) to DATABASE_URL with
    # "_test" appended to the database name, e.g. "insightforge" ->
    # "insightforge_test". Set explicitly to point somewhere else.
    TEST_DATABASE_URL: str = ""

    SECRET_KEY: str = "changeme"

    BACKEND_CORS_ORIGINS: list[str] = []

    YOUTUBE_API_KEY: str = ""
    YOUTUBE_VIDEO_CACHE_TTL_MINUTES: int = 60
    YOUTUBE_COMMENT_CACHE_TTL_MINUTES: int = 15
    YOUTUBE_SENTIMENT_COMMENT_LIMIT: int = 100

    TEXT_REMOVE_EMOJIS: bool = True
    TEXT_LOWERCASE: bool = True
    TEXT_LANGUAGE_MIN_CONFIDENCE: float = 0.7
    SUPPORTED_LANGUAGES: list[str] = ["ar", "en", "es", "fr", "de", "pt", "it"]

    # Pinned to the exact commit each model resolved to on the HuggingFace
    # Hub -- previously unpinned, meaning a silent upstream update to any of
    # these repos would have changed inference results without a
    # corresponding code change here.
    #
    # Arabic model restored (2026-08-07) to Ammar-alhaj-ali/arabic-MARBERT-
    # sentiment -- the model the earlier SentimentPro product proved out in
    # production, natively 3-class (positive/neutral/negative, unlike the
    # binary iMeshal model it replaces), so a genuinely neutral Arabic
    # comment no longer depends solely on the cascade/min-confidence gate to
    # avoid being forced into positive/negative.
    SENTIMENT_ARABIC_MODEL: str = "Ammar-alhaj-ali/arabic-MARBERT-sentiment"
    SENTIMENT_ARABIC_MODEL_REVISION: str | None = "db063587f876d5abcf6cdeed70648fc76a30349f"
    # English model switched (2026-08-08) to cardiffnlp/twitter-roberta-base-
    # sentiment-latest -- SentimentPro's proven English provider
    # (app/ai/providers/roberta_provider.py / app/core/config.py's
    # sentiment_model_name_en). Natively 3-class (negative/neutral/positive),
    # unlike the binary siebert model it replaces, so the "en" route now
    # allows a native neutral prediction the same way "ar"/"mixed" already
    # do (see app/services/sentiment/model.py's allow_neutral).
    SENTIMENT_ENGLISH_MODEL: str = "cardiffnlp/twitter-roberta-base-sentiment-latest"
    SENTIMENT_ENGLISH_MODEL_REVISION: str | None = "3216a57f2a0d9c45a2e6c20157c20c49fb4bf9c7"
    SENTIMENT_MIXED_MODEL: str = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
    SENTIMENT_MIXED_MODEL_REVISION: str | None = "f2f1202b1bdeb07342385c3f807f9c07cd8f5cf8"

    SENTIMENT_BATCH_SIZE: int = 16
    # Lowered 0.70 -> 0.55 (2026-08-08) to match SentimentPro's proven
    # production default (app/schemas/analysis.py's confidence_threshold
    # field and app/services/analysis_service.py's options.get fallback,
    # both 0.55). InsightForge's own 0.70 was a plain field default with no
    # test or comment tying it to an InsightForge-specific reason, so there
    # is no real conflict to preserve -- 0.55 is adopted directly. This
    # gates SentimentService.analyze's low_confidence -> "uncertain" fallback
    # (see app/services/sentiment/service.py), the same role SentimentPro's
    # confidence_threshold plays in resolve_sentiment_decision.
    SENTIMENT_MIN_CONFIDENCE: float = 0.55
    SENTIMENT_DEVICE: str = "auto"
    SENTIMENT_MAX_LENGTH: int = 512
    # Bounded wall-clock timeout for loading a single model (tokenizer +
    # weights, including any HF Hub network calls) -- without this, a
    # network black-hole (firewalled/unreachable host) can hang the worker
    # indefinitely since huggingface_hub's own HTTP calls have no
    # guaranteed upper bound in every code path. On timeout, the job fails
    # cleanly (SentimentModelLoadError) instead of hanging forever.
    SENTIMENT_MODEL_LOAD_TIMEOUT_SECONDS: int = 60

    # Job-level confidence_threshold override (Sprint 32) is validated against
    # this operational range, not the full 0.0-1.0 domain -- values outside it
    # would either gate almost nothing (near 0) or almost everything (near 1),
    # neither of which is a meaningful production choice.
    SENTIMENT_CONFIDENCE_THRESHOLD_MIN: float = 0.30
    SENTIMENT_CONFIDENCE_THRESHOLD_MAX: float = 0.90

    # Arabic fallback cascade: MARBERT (Ammar-alhaj-ali/arabic-MARBERT-
    # sentiment, natively 3-class) remains the sole primary Arabic model.
    # When enabled, a low-confidence-or-margin MARBERT result is re-scored
    # by the mixed-route XLM-R model as a second opinion -- whichever
    # prediction has higher confidence wins. This is a general uncertainty
    # safety net (dialectal/sarcastic/ambiguous Arabic), not a workaround
    # for a binary label space -- MARBERT's own native "neutral" label
    # already covers prayer/request/neutral comments via the
    # native_neutral uncertainty path in sentiment/service.py. Never
    # applied to the "en" or "mixed" routes.
    SENTIMENT_ARABIC_CASCADE_ENABLED: bool = True
    SENTIMENT_ARABIC_CASCADE_CONFIDENCE_THRESHOLD: float = 0.80
    SENTIMENT_ARABIC_CASCADE_MARGIN_THRESHOLD: float = 0.40

    # Confidence ceiling (Sprint 32): final fused confidence is capped here so
    # no result is ever reported as fully certain.
    SENTIMENT_CONFIDENCE_CEILING: float = 0.97

    # LLM escalation for HYBRID/SMART sentiment modes (Sprint 33). Reuses the
    # same GEMINI_API_KEY/OPENAI_API_KEY/INSIGHT_AI_*_MODEL settings the
    # insights AI providers already use -- no separate provider credentials.
    # FAST never reads any of these. temperature is fixed at 0.2 per spec,
    # independent of INSIGHT_AI_TEMPERATURE (a different feature).
    # Local-first by default: escalation must never depend on a cloud quota.
    # Accepted values: lmstudio | openai_compatible | openai | gemini | none.
    # The fallback is tried only when the primary is unconfigured or fails;
    # "none" is a valid, fully-supported value for both.
    SENTIMENT_LLM_PRIMARY_PROVIDER: str = "lmstudio"
    SENTIMENT_LLM_FALLBACK_PROVIDER: str = "none"
    # Any OpenAI-protocol endpoint: LM Studio, Ollama, vLLM, or a hosted Qwen
    # service. Changing these two lines is the whole of "move escalation to
    # production inference" -- no HYBRID/SMART logic depends on the backend.
    SENTIMENT_LLM_LOCAL_BASE_URL: str = "http://127.0.0.1:1234/v1"
    SENTIMENT_LLM_LOCAL_MODEL: str = "insightforge-qwen"
    # How many requests may be in flight against the local endpoint at once,
    # across ALL subsystems (Assistant, health canary, sentiment escalation,
    # insight discovery/synthesis). Set this to the endpoint's real slot
    # count, not higher: the subsystems have no knowledge of each other, and
    # an over-subscribed local endpoint slows every caller down together
    # rather than queueing politely. See app/services/llm/scheduler.py.
    #
    # 4 matches `lms ps` PARALLEL=4 for the loaded model. It was previously 1,
    # which was not a considered value -- it was the default, never set in
    # .env, and it did not matter because the subsystem that actually runs
    # several requests wide (discovery) bypassed the scheduler entirely.
    LLM_MAX_CONCURRENT_REQUESTS: int = 4
    # Slots withheld from escalation and background work so an interactive
    # Assistant turn never waits for a long batch to finish. Priority alone is
    # not enough: it orders the queue but cannot evict work already in flight.
    # With capacity 4 this leaves background at most 3 -- exactly the measured
    # safe shape (discovery 2 + escalation 1), with the fourth slot kept free.
    LLM_RESERVED_INTERACTIVE_SLOTS: int = 1
    # How long the health canary's verdict is trusted before re-probing. The
    # condition it detects (an endpoint returned to service partially
    # offloaded) persists, so re-probing often buys nothing.
    LLM_HEALTH_TTL_SECONDS: int = 300
    # Absolute per-job escalation ceilings (items, not percentages) and the
    # wall-clock safety net that stops a slow or hung provider from extending
    # a job indefinitely. See SentimentLLMConfig for why these are absolute.
    # Sized to the measured 0.94 items/s of the chosen batch size so the item
    # ceiling and the time ceiling agree on this hardware: 250 items ~= 265s,
    # 700 ~= 745s. An item budget the clock can never reach would be
    # decorative -- the time ceiling would silently do all the limiting and
    # the configured number would be a lie. Budgets are spent on DISTINCT
    # texts (escalation deduplicates first), so real coverage is higher than
    # these numbers on any corpus with repetition. Raise both when pointing at
    # a faster backend; the ratio, not the absolute value, defines the modes.
    # Escalation may ASK about any hard case, but may only OVERWRITE the
    # classifier when the classifier was not already confident.
    #
    # Sprint 35: re-derived after the emoji fix, which made FAST markedly
    # better at neutral (class F1 0.60 -> 0.86) and therefore moved the
    # crossover down. Measured over two full LLM runs on labeled_v2 (224
    # rows, 110 escalated, 51 disagreements), net useful-minus-harmful flips
    # by the confidence FAST already had:
    #
    #   0.00-0.55  +3     0.65-0.70  -2
    #   0.55-0.60  +1     0.70-0.75  -2
    #   0.60-0.65  +1     0.75-0.80  -3
    #   no-conf    +2     0.80-0.90  -6      >= 0.90  -5
    #
    # Sign changes exactly at 0.65 and stays negative above it, and the
    # accuracy sweep peaks at the same point in both runs (0.8304 / 0.8348
    # vs 0.7991 / 0.8170 at the old 0.80) -- so this is a real crossover
    # rather than a couple of lucky rows. The old 0.80 was correct for the
    # pre-fix classifier and is now simply too permissive: it lets the LLM
    # rewrite 0.65-0.80 answers that FAST is now usually getting right.
    # Set to 1.0 to let the LLM always override (pre-measurement behaviour).
    SENTIMENT_LLM_OVERRIDE_MIN_FAST_CONFIDENCE: float = 0.65
    SENTIMENT_LLM_HYBRID_MAX_ITEMS: int = 250
    SENTIMENT_LLM_SMART_MAX_ITEMS: int = 700
    SENTIMENT_LLM_HYBRID_TIME_BUDGET_SECONDS: int = 300
    SENTIMENT_LLM_SMART_TIME_BUDGET_SECONDS: int = 900
    # Zero, not 0.2: this is a CLASSIFICATION call, and the only thing
    # sampling adds is irreproducibility. Measured on the labeled benchmark,
    # two runs of the identical mode over identical inputs at 0.2 disagreed
    # by more than the gap between HYBRID and SMART (overall 0.749 vs 0.725;
    # the protected_intent stratum swung 0.821 vs 0.429). That makes results
    # unreviewable and means re-running an analysis can silently change a
    # user's labels. Greedy decoding removes the variance at no cost.
    SENTIMENT_LLM_TEMPERATURE: float = 0.0
    # Defaults below are measured against the local default backend (Qwen3-8B
    # Q4_K_M, 8192 ctx, RTX 3060 6GB), not inherited from the cloud era:
    #
    #   batch 10, concurrency 3, timeout 20s -> 5 of 6 batches TIMED OUT
    #   batch 10, concurrency 1              -> 0.45-0.54 items/s
    #   batch 20, concurrency 1              -> 0.78-0.94 items/s
    #   batch 25, concurrency 1              -> 0.74 items/s, 2/3 ok
    #
    # Concurrency above 1 does NOT increase throughput on a single local GPU:
    # llama.cpp serializes the work, so parallel requests only make each one
    # slower until they breach the timeout. Raise it only when pointing at a
    # hosted endpoint that genuinely serves requests in parallel.
    #
    # Batch size was tested as an ACCURACY question, not only a throughput
    # one -- items in one prompt do interfere with each other. Across 6 runs
    # of the labeled benchmark:
    #
    #                    accuracy   macro-F1   protected_intent   failures
    #   batch 20 (x4)      0.734      0.439         0.464          0 / 4
    #   batch 10 (x2)      0.743      0.425         0.732          1 per run
    #
    # Overall accuracy is a tie (the spread between identical re-runs is
    # ~1-5 points, comparable to the difference), macro-F1 favours batch 20,
    # and batch 20 completed every run without a failed batch while being
    # ~1.7x faster -- which is also ~2x the escalation coverage within the
    # same time budget. Batch 20 is kept.
    #
    # The one genuine finding from that experiment is NOT captured here: the
    # protected_intent stratum was consistently and substantially better at
    # batch 10 (0.732 vs an identical 0.464 across four batch-20 runs). That
    # is the dominant real comment category, so it is worth chasing -- but the
    # likely mechanism is WHICH comments share a prompt, not how many, and
    # testing similarity-grouped batching needs a larger benchmark than 171
    # rows to resolve. See scripts/sentiment_eval/README.md.
    SENTIMENT_LLM_TIMEOUT_SECONDS: int = 120
    SENTIMENT_LLM_MAX_RETRIES: int = 1
    SENTIMENT_LLM_BATCH_SIZE: int = 20
    SENTIMENT_LLM_MAX_CONCURRENCY: int = 1
    # 20 items x (label + confidence + short reason) fits comfortably; the
    # headroom exists because a truncated response fails the WHOLE batch,
    # which is a far worse trade than a few unused tokens.
    SENTIMENT_LLM_MAX_OUTPUT_TOKENS: int = 3000
    # Final-decision gate: the LLM label only replaces the FAST label when
    # llm_confidence is at or above this threshold (and the label/JSON are
    # valid) -- otherwise the FAST result is kept as-is.
    SENTIMENT_LLM_CONFIDENCE_THRESHOLD: float = 0.70
    # HYBRID-mode "hard case" thresholds (distinct from the final-decision
    # threshold above): a FAST result with confidence/margin below these is
    # considered escalation-worthy, in addition to sentiment=="uncertain",
    # sarcasm, Arabizi, complex contrast, ambiguous target, and cascade
    # disagreement.
    SENTIMENT_LLM_LOW_CONFIDENCE_THRESHOLD: float = 0.80
    SENTIMENT_LLM_LOW_MARGIN_THRESHOLD: float = 0.40

    MIXED_MIN_ARABIC_TOKENS: int = 1
    MIXED_MIN_ENGLISH_TOKENS: int = 2
    MIXED_MIN_SCRIPT_RATIO: float = 0.10
    MIXED_IGNORED_TECHNICAL_TERMS: list[str] = [
        "api",
        "apis",
        "python",
        "fastapi",
        "sql",
        "github",
        "git",
        "html",
        "css",
        "json",
        "http",
        "https",
        "url",
        "sdk",
        "cli",
        "ui",
        "ux",
        "id",
        "app",
        "youtube",
        "ai",
        "cpu",
        "gpu",
    ]

    # How many same-polarity emoji an EMOJI-ONLY comment needs before its
    # sentiment is read from the emoji. Sprint 35: lowered from 3 to 1.
    # At 3, "❤️❤️" and "😡😡" -- unambiguous two-emoji reactions -- came back
    # "uncertain", and a lone "👍" did too. When there is no text at all the
    # emoji are the only evidence there is, so demanding three of them threw
    # away real signal. Conflicting polarities still resolve to uncertain
    # (EMOJI_CONFLICT_MIN_COUNT), and genuinely ambivalent emoji (😭) are
    # handled separately, so this does not make 😭 alone a strong negative.
    # Measured: labeled_v2 accuracy UNCHANGED at 0.7991 (emoji-only comments
    # are a disjoint population from the text corpus), emoji regression set
    # 0.8148 -> 0.9630. Text-bearing comments are unaffected -- they never
    # reach this path.
    EMOJI_ONLY_MIN_COUNT: int = 1
    EMOJI_ONLY_CONFIDENCE: float = 0.75
    EMOJI_STRONG_BOOST: float = 0.03
    EMOJI_WEAK_BOOST: float = 0.015
    EMOJI_CONFLICT_MIN_COUNT: int = 1

    SPAM_WEAK_KEYWORD_MIN_HITS: int = 3
    SPAM_EXCESSIVE_EMOJI_COUNT: int = 12
    SPAM_REPEATED_CHAR_MIN_RUN: int = 8
    SPAM_LOW_UNIQUE_WORD_RATIO: float = 0.30
    SPAM_LOW_UNIQUE_WORD_MIN_LENGTH: int = 15
    SPAM_EXCESSIVE_CAPS_MIN_WORDS: int = 4

    SARCASM_SCORE_THRESHOLD: int = 3
    SARCASM_STRONG_SCORE_THRESHOLD: int = 5

    NEGATION_MAX_SCOPE_TOKENS: int = 6

    CONTRAST_POST_CLAUSE_WEIGHT: float = 1.5

    # New correction rules (Sprint 32). Each is a confidence *ceiling*: the
    # rule only ever fires below this value, so it can never override a
    # model result the pipeline is already confident about.
    GREETING_MAX_CONFIDENCE_OVERRIDE: float = 0.75
    OFF_TOPIC_MAX_CONFIDENCE_OVERRIDE: float = 0.75
    EMOTION_ONLY_MAX_CONFIDENCE_OVERRIDE: float = 0.70
    MIXED_OPINION_MAX_CONFIDENCE_OVERRIDE: float = 0.75
    MIXED_OPINION_BALANCE_GAP: float = 1.0

    TRIVIAL_SHORT_TEXT_MAX_WORDS: int = 2

    ANALYSIS_WORKER_POLL_INTERVAL_SECONDS: int = 5
    ANALYSIS_JOB_LEASE_SECONDS: int = 120
    ANALYSIS_JOB_MAX_ATTEMPTS: int = 3
    ANALYSIS_PROGRESS_UPDATE_INTERVAL: int = 1
    ANALYSIS_DEFAULT_COMMENT_LIMIT: int = 100
    ANALYSIS_MAX_COMMENT_LIMIT: int = 5000
    ANALYSIS_BATCH_SIZE: int = 200
    ANALYSIS_RETRY_BASE_DELAY_SECONDS: int = 5
    ANALYSIS_RETRY_MAX_DELAY_SECONDS: int = 300

    # Source quota waits (Phase 1). Distinct from the retry ladder above:
    # when a source tells us exactly when its quota resets (GitHub's
    # X-RateLimit-Reset / Retry-After), the job is rescheduled for that
    # instant and the wait does NOT consume one of ANALYSIS_JOB_MAX_ATTEMPTS
    # -- waiting is not failing, and GitHub's primary window (up to an hour)
    # is far longer than ANALYSIS_RETRY_MAX_DELAY_SECONDS, so the old ladder
    # burned every attempt inside a single reset window and failed the job
    # permanently. Bounded two ways so a permanently throttled source can
    # never park a job forever.
    ANALYSIS_QUOTA_WAIT_MAX_SINGLE_SECONDS: int = 3900
    ANALYSIS_QUOTA_WAIT_MAX_TOTAL_SECONDS: int = 21600
    # Floor on a quota wait, so a reset instant that has already elapsed (or
    # clock skew between us and the source) can never produce a hot loop of
    # immediate re-claims.
    ANALYSIS_QUOTA_WAIT_MIN_SECONDS: int = 15

    # Local-development convenience: runs app.workers.analysis_worker's
    # exact claim/lease/retry/execute loop on a background thread of the API
    # process itself (see app/workers/embedded.py), so `uvicorn --reload`
    # alone is enough to process jobs without a second terminal running
    # `python -m app.workers.analysis_worker`. The literal field default is
    # True, but _default_embedded_worker_to_development_only below narrows
    # that to "development only" whenever the variable is left unset --
    # explicitly setting it (either value) always wins. Not a substitute for
    # a dedicated worker process in production: a single thread cannot scale
    # horizontally, and it dies with the API process instead of restarting
    # independently. See app/workers/embedded.py's production warning log.
    ANALYSIS_EMBEDDED_WORKER_ENABLED: bool = True

    # ---- Insight AI providers (Sprint 12) ----
    # INSIGHT_AI_ENABLED=False disables AI/hybrid mode entirely regardless of
    # whether GEMINI_API_KEY/OPENAI_API_KEY are set -- local mode never reads
    # or requires these fields.
    INSIGHT_AI_ENABLED: bool = False
    INSIGHT_AI_PRIMARY_PROVIDER: Literal["lmstudio", "gemini", "openai"] = "lmstudio"
    INSIGHT_AI_FALLBACK_PROVIDER: Literal["lmstudio", "gemini", "openai", "none"] = "gemini"

    # SecretStr keeps these out of repr()/str()/logging by construction -- use
    # .get_secret_value() only at the point a provider client is actually built.
    GEMINI_API_KEY: SecretStr = SecretStr("")
    OPENAI_API_KEY: SecretStr = SecretStr("")

    # Blank means that provider is unavailable; no default is guessed here.
    INSIGHT_AI_GEMINI_MODEL: str = ""
    INSIGHT_AI_OPENAI_MODEL: str = ""

    INSIGHT_AI_LMSTUDIO_BASE_URL: str = "http://127.0.0.1:1234/v1"
    INSIGHT_AI_LMSTUDIO_MODEL: str = "insightforge-qwen"

    # A locally hosted 8B model emits roughly 8 structured-output tokens per
    # second, so a few thousand tokens takes several minutes. Sized against
    # that measured throughput rather than a hosted API's latency -- too low
    # and the largest synthesis request times out after producing nothing.
    INSIGHT_AI_TIMEOUT_SECONDS: int = 900
    # Retrying a local timeout just pays the same multi-minute cost again;
    # one retry bounds the worst case instead of tripling it.
    INSIGHT_AI_MAX_RETRIES: int = 1
    INSIGHT_AI_REPAIR_RETRIES: int = 1
    INSIGHT_AI_TEMPERATURE: float = 0.2
    # Must comfortably exceed the largest bounded response the provider
    # schemas can produce (see providers/lmstudio.py) -- a value below that
    # truncates the JSON mid-object and the whole attempt is wasted.
    INSIGHT_AI_MAX_OUTPUT_TOKENS: int = 4000
    INSIGHT_AI_MAX_INPUT_CHARACTERS: int = 60000
    # The provider's usable context window, which prompt AND completion share.
    # Must match what the model is actually loaded with (LM Studio reports it
    # as loaded_context_length) -- overstating it produces truncated JSON.
    INSIGHT_AI_CONTEXT_TOKENS: int = 8192
    INSIGHT_AI_MAX_CLUSTERS_PER_REQUEST: int = 24
    INSIGHT_AI_MAX_EVIDENCE_PER_CLUSTER: int = 4
    INSIGHT_AI_MAX_TOTAL_EVIDENCE: int = 60
    # Upper bound on how many clean comments the discovery stage reads in
    # total. Discovery batches this sample, so this directly caps how many
    # provider calls one analysis can cost.
    INSIGHT_AI_MAX_DISCOVERY_EVIDENCE: int = 180
    # How many discovery batches may be in flight at once. Discovery batches
    # are independent by construction (each reads its own slice of evidence and
    # contributes findings that are merged deterministically afterwards), so
    # this is pure wall-clock savings -- but only up to what the provider can
    # actually hold: LM Studio divides the loaded context window between
    # concurrent requests, so context_tokens must cover
    # concurrency x (prompt + completion) or every request past the first
    # fails with "Context size has been exceeded". AIConfig validates that.
    # 2, not 3: past 2 the wall-clock gain collapses (1.29x -> 1.41x) while
    # interactive Assistant latency nearly doubles (14.1s -> 25.7s), and 3
    # fills every LM Studio slot, leaving none for the Assistant or the
    # escalation health canary. See backend/.env for the measured table.
    INSIGHT_AI_DISCOVERY_CONCURRENCY: int = 2
    # Comments per discovery batch. Bigger batches mean fewer calls but force
    # the model to compress more comments into the same bounded finding list,
    # which costs recall; smaller batches keep recall but pay per-call
    # overhead. Benchmarked on the 1000-comment job (scripts/insight_bench).
    INSIGHT_AI_DISCOVERY_BATCH_ITEMS: int = 30
    INSIGHT_AI_STRICT_MODE: bool = False
    INSIGHT_AI_LOCAL_FALLBACK_ENABLED: bool = True
    INSIGHT_AI_PROMPT_VERSION: str = "v5"

    # ---- Local insight extraction (Sprint 12) ----
    INSIGHT_LOCAL_ENABLED: bool = True
    INSIGHT_EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    INSIGHT_EMBEDDING_DEVICE: str = "cpu"
    INSIGHT_EMBEDDING_BATCH_SIZE: int = 64
    INSIGHT_CLUSTER_MIN_SIZE: int = 3
    # Ceiling on evidence rows held in memory for one Insights run.
    # Measured at 9.08 KB resident per row, so 50k ~= 450 MB -- the point
    # past which an Insights page would start competing with the local LLM
    # for RAM. Jobs under this load in full and are unaffected; above it the
    # repository takes a deterministic stratified sample (see
    # AnalysisEvidenceRepository.get_for_job_bounded) while all counts and
    # percentages continue to come from the full population.
    INSIGHT_MAX_EVIDENCE_ROWS: int = 50_000
    INSIGHT_CLUSTER_MAX_TOPICS: int = 20
    INSIGHT_CLUSTER_SIMILARITY_THRESHOLD: float = 0.68
    INSIGHT_KEYWORD_LIMIT: int = 30
    INSIGHT_BIGRAM_LIMIT: int = 20
    INSIGHT_TRIGRAM_LIMIT: int = 10
    INSIGHT_EVIDENCE_LIMIT_PER_ITEM: int = 5
    # Sprint 34: bumped 1 -> 2. Cache key for GET/POST insights (see
    # AnalysisInsightRepository.get_cached/upsert) includes this value, so
    # bumping it invalidates every previously-cached insight result --
    # required because the Arabic intent/lexicon rules and prayer/request
    # separation changed this sprint (see app/services/text_intelligence/
    # intent.py, fusion.py), and a stale cached "no complaints found"
    # result generated under the old rules must not keep being served as
    # if it reflects the current engine.
    # Sprint 35: bumped 3 -> 4. Truncated LM Studio responses were cached as
    # empty "semantic analysis unavailable" results across every capability;
    # those rows must not keep being served now that discovery/synthesis
    # actually complete.
    # Generate the full Content Intelligence lineage during the analysis job
    # instead of on first page open.
    #
    # With this off, a completed analysis holds NO insight rows until a user
    # opens a capability page, which then blocks on a complete multi-batch
    # generation. That is why previously analysed videos appeared to "lose"
    # their intelligence: they had never been given any to keep. Generating
    # at job time makes every later read genuinely cache-only, which is what
    # lets History be a read-only snapshot.
    #
    # Failure here never fails the job -- the analysis, its sentiment and its
    # deterministic analytics are already committed before this runs.
    INSIGHT_GENERATE_ON_JOB_COMPLETION: bool = True

    INSIGHT_SCHEMA_VERSION: int = 4

    @field_validator(
        "INSIGHT_AI_TIMEOUT_SECONDS",
        "INSIGHT_AI_MAX_OUTPUT_TOKENS",
        "INSIGHT_AI_MAX_INPUT_CHARACTERS",
        "INSIGHT_AI_CONTEXT_TOKENS",
        "INSIGHT_AI_MAX_CLUSTERS_PER_REQUEST",
        "INSIGHT_AI_MAX_EVIDENCE_PER_CLUSTER",
        "INSIGHT_AI_MAX_TOTAL_EVIDENCE",
        "INSIGHT_AI_MAX_DISCOVERY_EVIDENCE",
        "INSIGHT_AI_DISCOVERY_CONCURRENCY",
        "INSIGHT_AI_DISCOVERY_BATCH_ITEMS",
        "INSIGHT_EMBEDDING_BATCH_SIZE",
        "INSIGHT_CLUSTER_MIN_SIZE",
        "INSIGHT_CLUSTER_MAX_TOPICS",
        "INSIGHT_KEYWORD_LIMIT",
        "INSIGHT_BIGRAM_LIMIT",
        "INSIGHT_TRIGRAM_LIMIT",
        "INSIGHT_EVIDENCE_LIMIT_PER_ITEM",
        "INSIGHT_SCHEMA_VERSION",
    )
    @classmethod
    def _validate_positive_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("INSIGHT_AI_MAX_RETRIES", "INSIGHT_AI_REPAIR_RETRIES")
    @classmethod
    def _validate_bounded_retry_count(cls, value: int, info) -> int:
        if not (0 <= value <= 10):
            raise ValueError(f"{info.field_name} must be between 0 and 10")
        return value

    @field_validator("INSIGHT_AI_TEMPERATURE")
    @classmethod
    def _validate_temperature(cls, value: float) -> float:
        if not (0.0 <= value <= 2.0):
            raise ValueError("INSIGHT_AI_TEMPERATURE must be between 0.0 and 2.0")
        return value

    @field_validator("INSIGHT_CLUSTER_SIMILARITY_THRESHOLD")
    @classmethod
    def _validate_similarity_threshold(cls, value: float) -> float:
        if not (0.0 <= value <= 1.0):
            raise ValueError("INSIGHT_CLUSTER_SIMILARITY_THRESHOLD must be between 0.0 and 1.0")
        return value

    @model_validator(mode="after")
    def _validate_provider_pair(self) -> "Settings":
        if (
            self.INSIGHT_AI_FALLBACK_PROVIDER != "none"
            and self.INSIGHT_AI_FALLBACK_PROVIDER == self.INSIGHT_AI_PRIMARY_PROVIDER
        ):
            raise ValueError(
                "INSIGHT_AI_PRIMARY_PROVIDER and INSIGHT_AI_FALLBACK_PROVIDER cannot be "
                "identical unless INSIGHT_AI_FALLBACK_PROVIDER is 'none'"
            )
        return self

    # ---- Authentication (Sprint 13) ----
    # Secrets are blank by default; see the model validator below for the
    # production-refuses / development-auto-generates policy. Never set a
    # real value here or in .env.example.
    AUTH_ACCESS_TOKEN_SECRET: SecretStr = SecretStr("")
    AUTH_ACCESS_TOKEN_ALGORITHM: Literal["HS256"] = "HS256"
    AUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    AUTH_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    AUTH_REFRESH_TOKEN_PEPPER: SecretStr = SecretStr("")
    AUTH_PASSWORD_MIN_LENGTH: int = 10
    AUTH_PASSWORD_MAX_LENGTH: int = 128
    AUTH_MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    AUTH_LOGIN_LOCKOUT_MINUTES: int = 15
    AUTH_REQUIRE_EMAIL_VERIFICATION: bool = False
    AUTH_ALLOW_REGISTRATION: bool = True
    AUTH_RATE_LIMIT_ENABLED: bool = True
    AUTH_TRUST_PROXY_HEADERS: bool = False

    AUTH_LOGIN_RATE_LIMIT_REQUESTS: int = 10
    AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 60
    AUTH_REGISTER_RATE_LIMIT_REQUESTS: int = 5
    AUTH_REGISTER_RATE_LIMIT_WINDOW_SECONDS: int = 3600
    ANALYSIS_CREATE_RATE_LIMIT_REQUESTS: int = 10
    ANALYSIS_CREATE_RATE_LIMIT_WINDOW_SECONDS: int = 60
    INSIGHT_GENERATE_RATE_LIMIT_REQUESTS: int = 20
    INSIGHT_GENERATE_RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ---- Per-user usage protection (Sprint 13, not billing) ----
    USAGE_MAX_ACTIVE_ANALYSIS_JOBS_PER_USER: int = 3
    USAGE_MAX_ANALYSIS_JOBS_PER_DAY: int = 25
    USAGE_MAX_COMMENT_LIMIT_PER_JOB: int = 1000

    # Set only by the model validator below -- true when a development
    # secret was auto-generated because none was configured. main.py's
    # startup logs a warning when this is set; never treated as an error
    # outside production.
    AUTH_ACCESS_TOKEN_SECRET_AUTO_GENERATED: bool = False
    AUTH_REFRESH_TOKEN_PEPPER_AUTO_GENERATED: bool = False
    AUTH_SECURITY_TOKEN_PEPPER_AUTO_GENERATED: bool = False
    RATE_LIMIT_IDENTITY_PEPPER_AUTO_GENERATED: bool = False
    AUTH_SESSION_FINGERPRINT_PEPPER_AUTO_GENERATED: bool = False

    @field_validator(
        "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES",
        "AUTH_REFRESH_TOKEN_EXPIRE_DAYS",
        "AUTH_PASSWORD_MIN_LENGTH",
        "AUTH_PASSWORD_MAX_LENGTH",
        "AUTH_MAX_FAILED_LOGIN_ATTEMPTS",
        "AUTH_LOGIN_LOCKOUT_MINUTES",
        "AUTH_LOGIN_RATE_LIMIT_REQUESTS",
        "AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS",
        "AUTH_REGISTER_RATE_LIMIT_REQUESTS",
        "AUTH_REGISTER_RATE_LIMIT_WINDOW_SECONDS",
        "ANALYSIS_CREATE_RATE_LIMIT_REQUESTS",
        "ANALYSIS_CREATE_RATE_LIMIT_WINDOW_SECONDS",
        "INSIGHT_GENERATE_RATE_LIMIT_REQUESTS",
        "INSIGHT_GENERATE_RATE_LIMIT_WINDOW_SECONDS",
        "USAGE_MAX_ACTIVE_ANALYSIS_JOBS_PER_USER",
        "USAGE_MAX_ANALYSIS_JOBS_PER_DAY",
        "USAGE_MAX_COMMENT_LIMIT_PER_JOB",
    )
    @classmethod
    def _validate_positive_bounded_auth_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES")
    @classmethod
    def _validate_access_token_expiry_bound(cls, value: int) -> int:
        if value > 24 * 60:
            raise ValueError("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES must be at most 1440 (24 hours)")
        return value

    @field_validator("AUTH_REFRESH_TOKEN_EXPIRE_DAYS")
    @classmethod
    def _validate_refresh_token_expiry_bound(cls, value: int) -> int:
        if value > 365:
            raise ValueError("AUTH_REFRESH_TOKEN_EXPIRE_DAYS must be at most 365")
        return value

    @model_validator(mode="after")
    def _validate_password_length_bounds(self) -> "Settings":
        if self.AUTH_PASSWORD_MIN_LENGTH < 8:
            raise ValueError("AUTH_PASSWORD_MIN_LENGTH must be at least 8")
        if self.AUTH_PASSWORD_MAX_LENGTH > 256:
            raise ValueError("AUTH_PASSWORD_MAX_LENGTH must be at most 256")
        if self.AUTH_PASSWORD_MAX_LENGTH <= self.AUTH_PASSWORD_MIN_LENGTH:
            raise ValueError(
                "AUTH_PASSWORD_MAX_LENGTH must be greater than AUTH_PASSWORD_MIN_LENGTH"
            )
        return self

    @model_validator(mode="after")
    def _validate_usage_limits_within_global_limits(self) -> "Settings":
        if self.USAGE_MAX_COMMENT_LIMIT_PER_JOB > self.ANALYSIS_MAX_COMMENT_LIMIT:
            raise ValueError(
                "USAGE_MAX_COMMENT_LIMIT_PER_JOB must not exceed ANALYSIS_MAX_COMMENT_LIMIT "
                f"({self.ANALYSIS_MAX_COMMENT_LIMIT})"
            )
        return self

    @model_validator(mode="after")
    def _default_test_database_url(self) -> "Settings":
        if not self.TEST_DATABASE_URL:
            parsed = urlparse(self.DATABASE_URL)
            db_name = parsed.path.lstrip("/")
            if db_name and not db_name.endswith("_test"):
                self.TEST_DATABASE_URL = parsed._replace(path=f"/{db_name}_test").geturl()
            else:
                self.TEST_DATABASE_URL = self.DATABASE_URL
        return self

    @model_validator(mode="after")
    def _validate_cors_wildcard_with_credentials(self) -> "Settings":
        # main.py always sets allow_credentials=True when CORS is enabled;
        # per the CORS spec a wildcard origin with credentials enabled is
        # both insecure and actually rejected by browsers, so refuse it here
        # rather than allow a silently-broken/insecure configuration.
        if "*" in self.BACKEND_CORS_ORIGINS:
            raise ValueError(
                "BACKEND_CORS_ORIGINS must not contain '*' -- this application always "
                "sends allow_credentials=True, and a wildcard origin combined with "
                "credentials is insecure and rejected by browsers. List explicit origins."
            )
        return self

    @model_validator(mode="after")
    def _validate_and_generate_auth_secrets(self) -> "Settings":
        is_production = self.ENVIRONMENT.lower() == "production"

        if not self.AUTH_ACCESS_TOKEN_SECRET.get_secret_value():
            if is_production:
                raise ValueError(
                    "AUTH_ACCESS_TOKEN_SECRET must be set in production. Generate one with: "
                    'python -c "import secrets; print(secrets.token_urlsafe(64))"'
                )
            self.AUTH_ACCESS_TOKEN_SECRET = SecretStr(secrets.token_urlsafe(64))
            self.AUTH_ACCESS_TOKEN_SECRET_AUTO_GENERATED = True
        elif len(self.AUTH_ACCESS_TOKEN_SECRET.get_secret_value()) < _MIN_AUTH_SECRET_LENGTH:
            raise ValueError(
                f"AUTH_ACCESS_TOKEN_SECRET must be at least {_MIN_AUTH_SECRET_LENGTH} characters"
            )

        if not self.AUTH_REFRESH_TOKEN_PEPPER.get_secret_value():
            if is_production:
                raise ValueError(
                    "AUTH_REFRESH_TOKEN_PEPPER must be set in production. Generate one with: "
                    'python -c "import secrets; print(secrets.token_urlsafe(64))"'
                )
            self.AUTH_REFRESH_TOKEN_PEPPER = SecretStr(secrets.token_urlsafe(64))
            self.AUTH_REFRESH_TOKEN_PEPPER_AUTO_GENERATED = True
        elif len(self.AUTH_REFRESH_TOKEN_PEPPER.get_secret_value()) < _MIN_AUTH_SECRET_LENGTH:
            raise ValueError(
                f"AUTH_REFRESH_TOKEN_PEPPER must be at least {_MIN_AUTH_SECRET_LENGTH} characters"
            )

        if not self.AUTH_SECURITY_TOKEN_PEPPER.get_secret_value():
            if is_production:
                raise ValueError(
                    "AUTH_SECURITY_TOKEN_PEPPER must be set in production. Generate one with: "
                    'python -c "import secrets; print(secrets.token_urlsafe(64))"'
                )
            self.AUTH_SECURITY_TOKEN_PEPPER = SecretStr(secrets.token_urlsafe(64))
            self.AUTH_SECURITY_TOKEN_PEPPER_AUTO_GENERATED = True
        elif len(self.AUTH_SECURITY_TOKEN_PEPPER.get_secret_value()) < _MIN_AUTH_SECRET_LENGTH:
            raise ValueError(
                f"AUTH_SECURITY_TOKEN_PEPPER must be at least {_MIN_AUTH_SECRET_LENGTH} characters"
            )

        for field_name, auto_flag_name in (
            ("RATE_LIMIT_IDENTITY_PEPPER", "RATE_LIMIT_IDENTITY_PEPPER_AUTO_GENERATED"),
            ("AUTH_SESSION_FINGERPRINT_PEPPER", "AUTH_SESSION_FINGERPRINT_PEPPER_AUTO_GENERATED"),
        ):
            current: SecretStr = getattr(self, field_name)
            if not current.get_secret_value():
                # RATE_LIMIT_IDENTITY_PEPPER additionally cannot auto-generate
                # in any non-development environment while the Redis backend
                # is active: an auto-generated value is process-local, so
                # every instance would hash the same client IP differently
                # and silently defeat cross-process rate-limit sharing.
                multi_instance_risk = (
                    field_name == "RATE_LIMIT_IDENTITY_PEPPER"
                    and self.RATE_LIMIT_BACKEND == "redis"
                    and self.ENVIRONMENT.lower() != "development"
                )
                if is_production:
                    raise ValueError(
                        f"{field_name} must be set in production. Generate one with: "
                        'python -c "import secrets; print(secrets.token_urlsafe(64))"'
                    )
                if multi_instance_risk:
                    raise ValueError(
                        "RATE_LIMIT_IDENTITY_PEPPER must be explicitly configured outside "
                        "local development when RATE_LIMIT_BACKEND='redis' -- an "
                        "auto-generated pepper is process-local and would silently break "
                        "shared rate-limit identity across multiple instances. Generate "
                        'one with: python -c "import secrets; print(secrets.token_urlsafe(64))"'
                    )
                setattr(self, field_name, SecretStr(secrets.token_urlsafe(64)))
                setattr(self, auto_flag_name, True)
            elif len(current.get_secret_value()) < _MIN_AUTH_SECRET_LENGTH:
                raise ValueError(
                    f"{field_name} must be at least {_MIN_AUTH_SECRET_LENGTH} characters"
                )

        return self

    @model_validator(mode="after")
    def _validate_secret_separation(self) -> "Settings":
        """Every explicitly-configured secret in _SECRET_SEPARATION_FIELDS
        must be distinct from every other -- reusing one pepper for two
        purposes means a compromise of one immediately compromises the
        other. Runs in every environment (not just production), but only
        compares values that were actually supplied: two independently
        auto-generated development secrets are never flagged.
        """
        seen: dict[str, str] = {}
        for field_name, auto_flag_name in _SECRET_SEPARATION_FIELDS:
            if getattr(self, auto_flag_name):
                continue
            value = getattr(self, field_name).get_secret_value()
            for other_field, other_value in seen.items():
                if value == other_value:
                    raise ValueError(
                        f"{field_name} must not reuse the same value as {other_field} -- "
                        "each auth secret must be independently generated"
                    )
            seen[field_name] = value
        return self

    # ---- Redis (Sprint 14) ----
    REDIS_ENABLED: bool = True
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CONNECT_TIMEOUT_SECONDS: int = 3
    REDIS_SOCKET_TIMEOUT_SECONDS: int = 3
    REDIS_HEALTHCHECK_INTERVAL_SECONDS: int = 30
    REDIS_KEY_PREFIX: str = "insightforge"

    RATE_LIMIT_BACKEND: Literal["redis", "memory"] = "redis"
    RATE_LIMIT_ALLOW_IN_MEMORY_FALLBACK: bool = True
    RATE_LIMIT_FAIL_OPEN: bool = False
    # Dedicated pepper for hashing unauthenticated rate-limit identities
    # (client IP). Never reused for JWT signing, refresh-token hashing, or
    # session fingerprinting -- a compromise of one pepper must not weaken
    # the others.
    RATE_LIMIT_IDENTITY_PEPPER: SecretStr = SecretStr("")

    AUTH_RESEND_VERIFICATION_RATE_LIMIT_REQUESTS: int = 3
    AUTH_RESEND_VERIFICATION_RATE_LIMIT_WINDOW_SECONDS: int = 3600
    AUTH_FORGOT_PASSWORD_RATE_LIMIT_REQUESTS: int = 3
    AUTH_FORGOT_PASSWORD_RATE_LIMIT_WINDOW_SECONDS: int = 3600
    AUTH_RESET_PASSWORD_RATE_LIMIT_REQUESTS: int = 5
    AUTH_RESET_PASSWORD_RATE_LIMIT_WINDOW_SECONDS: int = 3600
    ADMIN_MUTATION_RATE_LIMIT_REQUESTS: int = 20
    ADMIN_MUTATION_RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ---- Security tokens (Sprint 14 / 14.1) ----
    # Dedicated pepper for hashing email-verification and password-reset
    # tokens (UserSecurityToken.token_hash). Deliberately independent from
    # AUTH_REFRESH_TOKEN_PEPPER -- a compromise of one must not let an
    # attacker forge or brute-force the other class of token.
    AUTH_SECURITY_TOKEN_PEPPER: SecretStr = SecretStr("")
    AUTH_EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES: int = 30
    AUTH_EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS: int = 300
    AUTH_PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 20

    # ---- Session fingerprinting (Sprint 14) ----
    # Dedicated pepper for HMAC-hashing refresh-session IP/user-agent
    # metadata. Raw IP/user-agent values are never persisted.
    AUTH_SESSION_FINGERPRINT_PEPPER: SecretStr = SecretStr("")
    AUTH_SESSION_USER_AGENT_MAX_LENGTH: int = 512

    # ---- Security notifications (Sprint 14) ----
    AUTH_NOTIFY_ON_PASSWORD_CHANGE: bool = True
    AUTH_NOTIFY_ON_NEW_LOGIN: bool = False
    AUTH_NOTIFY_ON_REFRESH_REPLAY: bool = True

    # ---- Email delivery (Sprint 14) ----
    EMAIL_BACKEND: Literal["smtp", "console"] = "smtp"
    EMAIL_FROM_ADDRESS: str = "no-reply@insightforge.local"
    EMAIL_FROM_NAME: str = "InsightForge AI"
    EMAIL_SMTP_HOST: str = "localhost"
    EMAIL_SMTP_PORT: int = 1025
    EMAIL_SMTP_USERNAME: str = ""
    EMAIL_SMTP_PASSWORD: SecretStr = SecretStr("")
    EMAIL_SMTP_USE_TLS: bool = False
    EMAIL_SMTP_TIMEOUT_SECONDS: int = 10

    EMAIL_OUTBOX_WORKER_POLL_INTERVAL_SECONDS: int = 3
    EMAIL_OUTBOX_MAX_ATTEMPTS: int = 5
    EMAIL_OUTBOX_RETRY_BASE_DELAY_SECONDS: int = 30
    EMAIL_OUTBOX_RETRY_MAX_DELAY_SECONDS: int = 900

    # ---- Frontend links (Sprint 14) ----
    FRONTEND_PUBLIC_URL: str = "http://localhost:5173"
    AUTH_EMAIL_VERIFICATION_PATH: str = "/verify-email"
    AUTH_PASSWORD_RESET_PATH: str = "/reset-password"

    @field_validator(
        "REDIS_CONNECT_TIMEOUT_SECONDS",
        "REDIS_SOCKET_TIMEOUT_SECONDS",
        "REDIS_HEALTHCHECK_INTERVAL_SECONDS",
        "AUTH_RESEND_VERIFICATION_RATE_LIMIT_REQUESTS",
        "AUTH_RESEND_VERIFICATION_RATE_LIMIT_WINDOW_SECONDS",
        "AUTH_FORGOT_PASSWORD_RATE_LIMIT_REQUESTS",
        "AUTH_FORGOT_PASSWORD_RATE_LIMIT_WINDOW_SECONDS",
        "AUTH_RESET_PASSWORD_RATE_LIMIT_REQUESTS",
        "AUTH_RESET_PASSWORD_RATE_LIMIT_WINDOW_SECONDS",
        "ADMIN_MUTATION_RATE_LIMIT_REQUESTS",
        "ADMIN_MUTATION_RATE_LIMIT_WINDOW_SECONDS",
        "AUTH_EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES",
        "AUTH_EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS",
        "AUTH_PASSWORD_RESET_TOKEN_EXPIRE_MINUTES",
        "AUTH_SESSION_USER_AGENT_MAX_LENGTH",
        "EMAIL_SMTP_PORT",
        "EMAIL_SMTP_TIMEOUT_SECONDS",
        "EMAIL_OUTBOX_WORKER_POLL_INTERVAL_SECONDS",
        "EMAIL_OUTBOX_MAX_ATTEMPTS",
        "EMAIL_OUTBOX_RETRY_BASE_DELAY_SECONDS",
        "EMAIL_OUTBOX_RETRY_MAX_DELAY_SECONDS",
    )
    @classmethod
    def _validate_positive_sprint14_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("REDIS_URL")
    @classmethod
    def _validate_redis_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in ("redis", "rediss"):
            raise ValueError("REDIS_URL must start with redis:// or rediss://")
        if not parsed.hostname:
            raise ValueError("REDIS_URL must include a hostname")
        return value

    @field_validator("REDIS_KEY_PREFIX")
    @classmethod
    def _validate_redis_key_prefix(cls, value: str) -> str:
        if not value or not all(ch.isalnum() or ch in "_-" for ch in value):
            raise ValueError(
                "REDIS_KEY_PREFIX must be non-empty and contain only letters, digits, '_' or '-'"
            )
        return value

    @field_validator("FRONTEND_PUBLIC_URL")
    @classmethod
    def _validate_frontend_public_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("FRONTEND_PUBLIC_URL must be an absolute http:// or https:// URL")
        return value

    @field_validator("AUTH_EMAIL_VERIFICATION_PATH", "AUTH_PASSWORD_RESET_PATH")
    @classmethod
    def _validate_frontend_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("Frontend paths must start with '/'")
        return value

    @model_validator(mode="after")
    def _default_embedded_worker_to_development_only(self) -> "Settings":
        # model_fields_set only contains names explicitly provided via env/
        # init -- an operator who actually sets ANALYSIS_EMBEDDED_WORKER_ENABLED
        # (true or false) always gets exactly that value, in any environment.
        # Only the unset case is narrowed here, from the field's plain
        # default of True down to "development only".
        if "ANALYSIS_EMBEDDED_WORKER_ENABLED" not in self.model_fields_set:
            self.ANALYSIS_EMBEDDED_WORKER_ENABLED = self.ENVIRONMENT.lower() == "development"
        return self

    @model_validator(mode="after")
    def _validate_redis_backend_consistency(self) -> "Settings":
        if self.RATE_LIMIT_BACKEND == "redis" and not self.REDIS_ENABLED:
            raise ValueError(
                "RATE_LIMIT_BACKEND='redis' requires REDIS_ENABLED=true -- set "
                "RATE_LIMIT_BACKEND='memory' or enable Redis"
            )
        return self

    @model_validator(mode="after")
    def _validate_production_frontend_url(self) -> "Settings":
        if self.ENVIRONMENT.lower() == "production":
            parsed = urlparse(self.FRONTEND_PUBLIC_URL)
            if parsed.scheme != "https":
                raise ValueError("FRONTEND_PUBLIC_URL must use https:// in production")
            if parsed.hostname in ("localhost", "127.0.0.1"):
                raise ValueError("FRONTEND_PUBLIC_URL must not be localhost in production")
        return self

    @model_validator(mode="after")
    def _validate_smtp_backend_in_production(self) -> "Settings":
        if self.ENVIRONMENT.lower() == "production" and self.EMAIL_BACKEND == "console":
            raise ValueError(
                "EMAIL_BACKEND='console' is not allowed in production -- it writes email "
                "content (including tokens) to process logs. Configure EMAIL_BACKEND='smtp'."
            )
        return self

    # ---- Multi-source domain (Sprint 15) ----
    SOURCE_COLLECTION_BATCH_SIZE: int = 100
    SOURCE_RECORD_TEXT_MAX_LENGTH: int = 20000
    SOURCE_METADATA_MAX_BYTES: int = 8192
    SOURCE_CHECKPOINT_ENABLED: bool = True
    SOURCE_CONNECTOR_VERSION: str = "1"
    SOURCE_DATASET_PAGE_SIZE: int = 20

    @field_validator(
        "SOURCE_COLLECTION_BATCH_SIZE",
        "SOURCE_RECORD_TEXT_MAX_LENGTH",
        "SOURCE_METADATA_MAX_BYTES",
        "SOURCE_DATASET_PAGE_SIZE",
    )
    @classmethod
    def _validate_positive_source_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    # ---- File import connector (Sprint 16) ----
    FILE_IMPORT_ENABLED: bool = True
    FILE_IMPORT_STORAGE_BACKEND: Literal["local"] = "local"
    FILE_IMPORT_STORAGE_PATH: str = "var/file_imports"
    FILE_IMPORT_MAX_FILE_SIZE_MB: int = 25
    FILE_IMPORT_MAX_ROWS: int = 100_000
    FILE_IMPORT_MAX_COLUMNS: int = 100
    FILE_IMPORT_MAX_CELL_CHARACTERS: int = 10_000
    FILE_IMPORT_MAX_JSON_DEPTH: int = 5
    FILE_IMPORT_PROFILE_ROWS: int = 200
    FILE_IMPORT_BATCH_SIZE: int = 500
    FILE_IMPORT_RETENTION_HOURS: int = 24
    FILE_IMPORT_ALLOWED_FORMATS: list[str] = ["csv", "xlsx", "json"]

    FILE_IMPORT_CSV_DELIMITER_AUTO_DETECT: bool = True
    FILE_IMPORT_CSV_ALLOWED_DELIMITERS: list[str] = [",", ";", "\t", "|"]
    FILE_IMPORT_CSV_ALLOWED_ENCODINGS: list[str] = ["utf-8", "utf-8-sig"]

    FILE_IMPORT_XLSX_MAX_SHEETS: int = 20
    FILE_IMPORT_XLSX_MAX_SHARED_STRINGS: int = 200_000
    FILE_IMPORT_XLSX_MAX_UNCOMPRESSED_BYTES: int = 300 * 1024 * 1024
    FILE_IMPORT_XLSX_MAX_COMPRESSION_RATIO: float = 100.0

    FILE_IMPORT_INVALID_ROW_POLICY: Literal["skip"] = "skip"
    FILE_IMPORT_MAX_INVALID_ROWS: int = 50_000
    FILE_IMPORT_MAX_PERSISTED_ROW_ERRORS: int = 1000
    FILE_IMPORT_FAIL_ON_ERROR_RATIO: float = 0.5

    FILE_IMPORT_MAX_ACTIVE_IMPORTS_PER_USER: int = 5
    FILE_IMPORT_MAX_STORED_BYTES_PER_USER: int = 250 * 1024 * 1024
    FILE_IMPORT_MAX_BYTES_PER_USER_PER_DAY: int = 500 * 1024 * 1024
    FILE_IMPORT_UPLOAD_RATE_LIMIT_REQUESTS: int = 10
    FILE_IMPORT_UPLOAD_RATE_LIMIT_WINDOW_SECONDS: int = 3600

    # Universal Dataset Intelligence (app/datasets). Every bound the engine
    # obeys is here rather than inside an analysis stage, so cost can be
    # tuned per deployment without editing analysis code.
    DATASET_INTELLIGENCE_ENABLED: bool = True
    # Rows held in memory for profiling. Beyond this the loader switches to
    # deterministic systematic sampling and the report SAYS SO (see
    # DatasetCoverage) -- exact row/missing/duplicate counts are still
    # computed over the full population in the streaming pass.
    DATASET_MAX_ANALYSIS_ROWS: int = 50_000
    DATASET_SAMPLE_VALUES: int = 5
    DATASET_TOP_CATEGORIES: int = 10
    # At or below this many distinct values a string column is treated as a
    # categorical dimension rather than free text.
    DATASET_MAX_CATEGORICAL_UNIQUE: int = 50
    DATASET_HIGH_CARDINALITY_RATIO: float = 0.5
    DATASET_OUTLIER_IQR_MULTIPLIER: float = 1.5
    # Correlation is O(n^2) in columns. Capping the numeric columns entered
    # into the matrix is what stops a 100-column upload from computing 4,950
    # pairs; partial coverage is disclosed rather than hidden.
    DATASET_CORRELATION_MAX_COLUMNS: int = 25
    DATASET_CORRELATION_MIN_ROWS: int = 20
    DATASET_CORRELATION_MIN_ABS: float = 0.3
    DATASET_GROUP_COMPARISON_MAX_PAIRS: int = 12
    DATASET_MAX_TEXT_COLUMNS: int = 3
    DATASET_TEXT_ROWS_PER_COLUMN: int = 2000
    DATASET_TEXT_MIN_AVERAGE_LENGTH: int = 25
    DATASET_PREVIEW_ROWS: int = 20
    DATASET_TEMPORAL_MIN_POINTS: int = 3

    @field_validator(
        "DATASET_MAX_ANALYSIS_ROWS",
        "DATASET_SAMPLE_VALUES",
        "DATASET_TOP_CATEGORIES",
        "DATASET_MAX_CATEGORICAL_UNIQUE",
        "DATASET_CORRELATION_MAX_COLUMNS",
        "DATASET_CORRELATION_MIN_ROWS",
        "DATASET_GROUP_COMPARISON_MAX_PAIRS",
        "DATASET_MAX_TEXT_COLUMNS",
        "DATASET_TEXT_ROWS_PER_COLUMN",
        "DATASET_TEXT_MIN_AVERAGE_LENGTH",
        "DATASET_PREVIEW_ROWS",
        "DATASET_TEMPORAL_MIN_POINTS",
    )
    @classmethod
    def _validate_positive_dataset_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator(
        "DATASET_HIGH_CARDINALITY_RATIO",
        "DATASET_CORRELATION_MIN_ABS",
    )
    @classmethod
    def _validate_dataset_ratio(cls, value: float, info) -> float:
        if not 0.0 < value <= 1.0:
            raise ValueError(f"{info.field_name} must be between 0 and 1")
        return value

    @field_validator("DATASET_OUTLIER_IQR_MULTIPLIER")
    @classmethod
    def _validate_outlier_multiplier(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("DATASET_OUTLIER_IQR_MULTIPLIER must be greater than 0")
        return value

    @field_validator(
        "FILE_IMPORT_MAX_FILE_SIZE_MB",
        "FILE_IMPORT_MAX_ROWS",
        "FILE_IMPORT_MAX_COLUMNS",
        "FILE_IMPORT_MAX_CELL_CHARACTERS",
        "FILE_IMPORT_MAX_JSON_DEPTH",
        "FILE_IMPORT_PROFILE_ROWS",
        "FILE_IMPORT_BATCH_SIZE",
        "FILE_IMPORT_RETENTION_HOURS",
        "FILE_IMPORT_XLSX_MAX_SHEETS",
        "FILE_IMPORT_XLSX_MAX_SHARED_STRINGS",
        "FILE_IMPORT_XLSX_MAX_UNCOMPRESSED_BYTES",
        "FILE_IMPORT_MAX_INVALID_ROWS",
        "FILE_IMPORT_MAX_PERSISTED_ROW_ERRORS",
        "FILE_IMPORT_MAX_ACTIVE_IMPORTS_PER_USER",
        "FILE_IMPORT_MAX_STORED_BYTES_PER_USER",
        "FILE_IMPORT_MAX_BYTES_PER_USER_PER_DAY",
        "FILE_IMPORT_UPLOAD_RATE_LIMIT_REQUESTS",
        "FILE_IMPORT_UPLOAD_RATE_LIMIT_WINDOW_SECONDS",
    )
    @classmethod
    def _validate_positive_file_import_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("FILE_IMPORT_XLSX_MAX_COMPRESSION_RATIO")
    @classmethod
    def _validate_compression_ratio(cls, value: float) -> float:
        if value <= 1.0:
            raise ValueError("FILE_IMPORT_XLSX_MAX_COMPRESSION_RATIO must be greater than 1.0")
        return value

    @field_validator("FILE_IMPORT_FAIL_ON_ERROR_RATIO")
    @classmethod
    def _validate_fail_on_error_ratio(cls, value: float) -> float:
        if not (0.0 < value <= 1.0):
            raise ValueError("FILE_IMPORT_FAIL_ON_ERROR_RATIO must be between 0 and 1")
        return value

    @field_validator("FILE_IMPORT_ALLOWED_FORMATS")
    @classmethod
    def _validate_allowed_import_formats(cls, value: list[str]) -> list[str]:
        allowed = {"csv", "xlsx", "json"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"FILE_IMPORT_ALLOWED_FORMATS contains unsupported values: {unknown}")
        return value

    @field_validator("FILE_IMPORT_CSV_ALLOWED_DELIMITERS")
    @classmethod
    def _validate_csv_delimiters(cls, value: list[str]) -> list[str]:
        if not value or any(len(delimiter) != 1 for delimiter in value):
            raise ValueError(
                "FILE_IMPORT_CSV_ALLOWED_DELIMITERS must be a non-empty list of single characters"
            )
        return value

    @field_validator("FILE_IMPORT_CSV_ALLOWED_ENCODINGS")
    @classmethod
    def _validate_csv_encodings(cls, value: list[str]) -> list[str]:
        unknown = {encoding.lower() for encoding in value} - _SAFE_IMPORT_TEXT_ENCODINGS
        if not value or unknown:
            raise ValueError(
                "FILE_IMPORT_CSV_ALLOWED_ENCODINGS must be non-empty and drawn from "
                f"{sorted(_SAFE_IMPORT_TEXT_ENCODINGS)}"
            )
        return value

    @model_validator(mode="after")
    def _validate_file_import_storage_path(self) -> "Settings":
        if self.FILE_IMPORT_ENABLED and not self.FILE_IMPORT_STORAGE_PATH.strip():
            raise ValueError("FILE_IMPORT_STORAGE_PATH must be set when FILE_IMPORT_ENABLED=true")
        return self

    # ---- Structured signal intelligence (Sprint 17) ----
    SIGNAL_INTELLIGENCE_ENABLED: bool = True
    SIGNAL_MIN_GROUP_SIZE: int = 2
    # Evidence rows held in memory at once while generating signals. Signal
    # results are computed over the FULL population regardless of this value
    # -- it controls only how many ORM rows are resident at a time (measured
    # 8.99 KB each), not how many are counted. 2000 keeps the resident set
    # near 18 MB on a job of any size.
    SIGNAL_EVIDENCE_BATCH_SIZE: int = 2000
    SIGNAL_MAX_SIGNALS_PER_JOB: int = 100
    SIGNAL_MAX_EVIDENCE_PER_SIGNAL: int = 20
    SIGNAL_GROUPING_THRESHOLD: float = 0.5
    SIGNAL_MIN_CONFIDENCE: float = 0.35
    SIGNAL_RECOMMENDATIONS_MAX_PER_SIGNAL: int = 5
    SIGNAL_PRIORITY_SCORING_VERSION: str = "v1"
    SIGNAL_ALGORITHM_VERSION: str = "v1"

    SIGNAL_PROVIDER_ENRICHMENT_ENABLED: bool = True
    SIGNAL_PROVIDER_BATCH_SIZE: int = 5
    SIGNAL_PROVIDER_TIMEOUT_SECONDS: int = 30
    SIGNAL_PROVIDER_MAX_RETRIES: int = 1
    SIGNAL_PROVIDER_MAX_EVIDENCE_EXCERPTS: int = 5
    SIGNAL_PROVIDER_MAX_EXCERPT_CHARS: int = 200

    # Weighted priority components (Sprint 17 Part 6) -- must sum to 1.0.
    SIGNAL_PRIORITY_WEIGHT_FREQUENCY: float = 0.30
    SIGNAL_PRIORITY_WEIGHT_SEVERITY: float = 0.25
    SIGNAL_PRIORITY_WEIGHT_RECENCY: float = 0.15
    SIGNAL_PRIORITY_WEIGHT_IMPACT: float = 0.20
    SIGNAL_PRIORITY_WEIGHT_CONFIDENCE: float = 0.10

    @field_validator(
        "SIGNAL_MIN_GROUP_SIZE",
        "SIGNAL_MAX_SIGNALS_PER_JOB",
        "SIGNAL_MAX_EVIDENCE_PER_SIGNAL",
        "SIGNAL_RECOMMENDATIONS_MAX_PER_SIGNAL",
        "SIGNAL_PROVIDER_BATCH_SIZE",
        "SIGNAL_PROVIDER_TIMEOUT_SECONDS",
        "SIGNAL_PROVIDER_MAX_EVIDENCE_EXCERPTS",
        "SIGNAL_PROVIDER_MAX_EXCERPT_CHARS",
    )
    @classmethod
    def _validate_positive_signal_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("SIGNAL_PROVIDER_MAX_RETRIES")
    @classmethod
    def _validate_signal_max_retries(cls, value: int) -> int:
        if not (0 <= value <= 10):
            raise ValueError("SIGNAL_PROVIDER_MAX_RETRIES must be between 0 and 10")
        return value

    @field_validator("SIGNAL_GROUPING_THRESHOLD", "SIGNAL_MIN_CONFIDENCE")
    @classmethod
    def _validate_unit_interval_signal_float(cls, value: float, info) -> float:
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"{info.field_name} must be between 0.0 and 1.0")
        return value

    @field_validator(
        "SIGNAL_PRIORITY_WEIGHT_FREQUENCY",
        "SIGNAL_PRIORITY_WEIGHT_SEVERITY",
        "SIGNAL_PRIORITY_WEIGHT_RECENCY",
        "SIGNAL_PRIORITY_WEIGHT_IMPACT",
        "SIGNAL_PRIORITY_WEIGHT_CONFIDENCE",
    )
    @classmethod
    def _validate_priority_weight(cls, value: float, info) -> float:
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"{info.field_name} must be between 0.0 and 1.0")
        return value

    # ---- GitHub connector (Sprint 18) ----
    # CONNECTOR_CREDENTIAL_ENCRYPTION_KEY is a SECRET -- see the model
    # validator below for the production-refuses / development-auto-generates
    # policy (mirrors AUTH_ACCESS_TOKEN_SECRET). Restarting a development
    # process with an auto-generated key makes every previously-stored
    # credential undecryptable -- acceptable for local dev, refused in
    # production.
    GITHUB_CONNECTOR_ENABLED: bool = False
    GITHUB_API_BASE_URL: str = "https://api.github.com"
    GITHUB_API_VERSION: str = "2022-11-28"
    # SECRET. A server-level GitHub personal access token used as the DEFAULT
    # credential when a request carries no per-user one. SecretStr keeps it
    # out of repr()/str()/logging by construction -- use .get_secret_value()
    # only at the point the Authorization header is actually built (see
    # GitHubClient._effective_token), exactly like GEMINI_API_KEY.
    #
    # Empty (the default) preserves today's behavior exactly: requests go out
    # unauthenticated and public repositories still work, just on GitHub's
    # much smaller anonymous quota.
    #
    # Precedence: a per-user connection credential ALWAYS wins. This is only
    # the fallback for requests that have none.
    #
    # Deployment note -- this token is NOT user-scoped. Every request that
    # lacks a per-user credential is made as this token's account, so on a
    # multi-user instance any user could reach whatever it can read. Give it
    # public-repository access only, and use per-user connections
    # (POST /api/v1/sources/github/connections) for private repositories,
    # which stay scoped to the user who supplied them.
    GITHUB_TOKEN: SecretStr = SecretStr("")
    GITHUB_REQUEST_TIMEOUT_SECONDS: int = 15
    GITHUB_MAX_RETRIES: int = 2
    # GitHub's own documented maximum for every paginated endpoint this
    # connector uses. This is pagination GEOMETRY, not a budget: it is sent
    # as `per_page` on every request of a phase and must never vary within
    # one pagination sequence, because `page=N` addresses a different window
    # when `per_page` changes (that mismatch silently skipped records before
    # Phase 1 -- see GitHubConnector._collect_phase).
    GITHUB_COLLECTION_PAGE_SIZE: int = 100
    # How many pull requests one collect_page call processes while gathering
    # reviews. Purely a per-call work bound so a single call stays inside
    # the job lease -- NOT a ceiling on how many PRs are ever reviewed.
    #
    # Raised from 10 to 25 on measured evidence. A review request against the
    # live API averaged 800 ms (six calls, diegosouzapw/OmniRoute), so:
    #
    #   quantum 10 -> ~8 s of API work per worker iteration
    #   quantum 25 -> ~20 s of API work per worker iteration
    #
    # against a 120 s job lease (ANALYSIS_JOB_LEASE_SECONDS), which the
    # runner renews on every iteration. 20 s leaves a wide margin for a slow
    # response while cutting orchestration cycles -- and cursor writes, and
    # transaction commits -- by 60%.
    #
    # Deliberately NOT larger. The cap that matters is not the lease but the
    # checkpoint interval: everything since the last persisted cursor is
    # re-done after a crash, so a quantum of 100 would mean re-fetching up to
    # 100 pull requests' reviews -- around 80 seconds of re-work, and 100
    # requests of an authenticated 5,000/hour quota, for nothing.
    GITHUB_REVIEW_PRS_PER_PAGE: int = 25
    # A short, in-request wait GitHub itself asked for (secondary rate limit
    # `Retry-After`) is simply honoured inline. Anything longer is escalated
    # to the job runner as a quota wait so the worker is never blocked --
    # see GitHubClient._request and SourceQuotaExhaustedError.
    GITHUB_INLINE_RETRY_MAX_WAIT_SECONDS: int = 30
    GITHUB_RETRY_BASE_DELAY_SECONDS: float = 0.5
    # Conditional requests (ETag / If-None-Match), deliberately scoped to
    # repository metadata only. A 304 there avoids transferring and parsing
    # the body and lets a repeat analysis keep the metadata it already had;
    # measured against the real API it does NOT save primary quota, so this
    # is a fidelity/bandwidth feature, not a quota one. List pages are
    # excluded on purpose: their ETag changes whenever any item on the page
    # changes, so they would almost always miss on an active repository
    # while adding a real correctness risk to resumable pagination.
    # Correctness over caching (Phase 1 audit item 22).
    GITHUB_CONDITIONAL_REQUESTS_ENABLED: bool = True

    # ---- Repository documents (Phase 3) ----
    # Human-readable project documentation (README, docs/, CONTRIBUTING, ...)
    # collected as ordinary source records. Not source-code ingestion: see
    # app/connectors/github_documents.py for the policy that decides what
    # counts as documentation.
    GITHUB_INCLUDE_DOCUMENTS: bool = True
    # Cost shape: ONE recursive tree request for the whole repository, then
    # at most GITHUB_MAX_DOCUMENTS blob requests. The candidate set is
    # filtered from the tree BEFORE any content is fetched, so the request
    # count depends on how much documentation a repository has, never on how
    # large the repository is.
    GITHUB_MAX_DOCUMENTS: int = 40
    # Per-file ceiling applied to the tree's own `size`, so an oversized file
    # is skipped without ever being downloaded.
    GITHUB_DOCUMENT_MAX_BYTES: int = 262_144
    # Whole-run ceiling, so a repository with many large documents cannot
    # produce an unbounded amount of analysis content.
    GITHUB_DOCUMENTS_TOTAL_MAX_BYTES: int = 2_097_152
    CONNECTOR_CREDENTIAL_ENCRYPTION_KEY: SecretStr = SecretStr("")
    CONNECTOR_CREDENTIAL_ENCRYPTION_KEY_AUTO_GENERATED: bool = False

    # ---- Reddit connector ----
    #
    # Every bound the Reddit connector observes is named here rather than
    # inlined at a call site. The reason is operational: the safe ceiling
    # for one deployment's Reddit app is not the safe ceiling for another's,
    # and a magic number buried in a collection loop cannot be raised
    # without a code change.
    REDDIT_CONNECTOR_ENABLED: bool = False
    REDDIT_API_BASE_URL: str = "https://oauth.reddit.com"
    REDDIT_OAUTH_TOKEN_URL: str = "https://www.reddit.com/api/v1/access_token"
    REDDIT_CLIENT_ID: str = ""
    # SECRET. SecretStr keeps it out of repr()/str()/logging by
    # construction -- .get_secret_value() is called only where the OAuth
    # request body is built (see RedditClient._fetch_token), exactly like
    # GITHUB_TOKEN.
    #
    # Empty is valid for an INSTALLED (mobile/browser) app type, which
    # authenticates with an empty secret. It is NOT valid for a script or
    # web app, and Reddit answers 401 -- surfaced as RedditAuthError with
    # that explanation rather than as a generic failure.
    REDDIT_CLIENT_SECRET: SecretStr = SecretStr("")
    # Reddit REQUIRES a descriptive, unique User-Agent and rate-limits
    # generic ones aggressively. Their documented format is
    # "<platform>:<app id>:<version> (by /u/<reddit username>)".
    REDDIT_USER_AGENT: str = "insightforge/1.0 (by /u/insightforge)"
    REDDIT_REQUEST_TIMEOUT_SECONDS: int = 20
    REDDIT_MAX_RETRIES: int = 2
    REDDIT_RETRY_BASE_DELAY_SECONDS: float = 0.75
    # How long a 429/exhausted-quota wait may be absorbed INLINE before the
    # connector gives up and hands the job runner a
    # SourceQuotaExhaustedError to schedule properly. Short waits are
    # cheaper to sit out than to re-queue; long ones are not.
    REDDIT_INLINE_RETRY_MAX_WAIT_SECONDS: int = 30
    # Reddit's own documented maximum for `limit` on listing endpoints.
    # Pagination GEOMETRY, not a budget -- see GITHUB_COLLECTION_PAGE_SIZE
    # for why these must never vary within one pagination sequence.
    REDDIT_LISTING_PAGE_SIZE: int = 100
    # Absolute ceiling on analyzable records (posts + comments + replies)
    # for ONE Reddit analysis, regardless of what the user asked for. This
    # is the safety cap named in the product spec.
    REDDIT_MAX_RECORDS_PER_ANALYSIS: int = 5000
    # Subreddit mode: how many posts may be collected. The UI offers
    # 10/25/50; this is the hard ceiling behind that choice.
    REDDIT_MAX_POSTS_PER_SUBREDDIT: int = 50
    REDDIT_DEFAULT_POSTS_PER_SUBREDDIT: int = 25
    # Per-post comment ceiling in subreddit mode, so one enormous thread
    # cannot consume the whole record budget and leave the other posts
    # unrepresented. Post mode has no such split and uses the analysis cap.
    REDDIT_MAX_COMMENTS_PER_POST: int = 500
    # Reddit collapses deep comment trees into "load more" stubs. This is
    # how many of those stubs one collection will expand. Each expansion is
    # a request, so it is a request budget, not a depth limit.
    REDDIT_MAX_MORE_CHILDREN_REQUESTS: int = 40
    # `morechildren` accepts many ids per call; Reddit's documented cap is
    # 100.
    REDDIT_MORE_CHILDREN_BATCH_SIZE: int = 100
    # Stop expanding replies below this depth. Reddit trees can be
    # arbitrarily deep and the deepest nodes are almost always two-word
    # exchanges -- past this point each request buys structure, not signal.
    REDDIT_MAX_COMMENT_DEPTH: int = 10
    # Slow down (rather than hammer) once the remaining quota falls below
    # this fraction of the window's limit. Being rate-limit AWARE is the
    # point: the connector should see exhaustion coming.
    REDDIT_RATE_LIMIT_SLOWDOWN_THRESHOLD: float = 0.15

    @field_validator(
        "GITHUB_REQUEST_TIMEOUT_SECONDS",
        "GITHUB_COLLECTION_PAGE_SIZE",
        "GITHUB_REVIEW_PRS_PER_PAGE",
    )
    @classmethod
    def _validate_positive_github_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("GITHUB_TOKEN")
    @classmethod
    def _sanitize_github_token(cls, value: SecretStr) -> SecretStr:
        """Removes whitespace and control characters from the token.

        The value is interpolated directly into an Authorization header, so
        CR/LF in it is the classic header-injection shape -- and a trailing
        newline is exactly what copy-pasting into a .env file produces. This
        strips them structurally, which makes the injection impossible rather
        than merely unlikely.

        Sanitizing rather than REJECTING is deliberate. Raising here would
        surface as a pydantic ValidationError, and pydantic echoes the
        offending `input_value` into that error -- so the "fail loudly"
        version of this validator would print the token into the startup log,
        which is precisely what it is supposed to prevent. A token that was
        malformed enough to be changed by this will simply not authenticate,
        and GitHub answers 401 -> GitHubAuthError, which carries no value.
        """
        cleaned = "".join(
            char for char in value.get_secret_value() if not char.isspace() and ord(char) >= 0x20
        )
        return SecretStr(cleaned)

    @field_validator(
        "GITHUB_MAX_DOCUMENTS",
        "GITHUB_DOCUMENT_MAX_BYTES",
        "GITHUB_DOCUMENTS_TOTAL_MAX_BYTES",
    )
    @classmethod
    def _validate_positive_github_document_bound(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("GITHUB_COLLECTION_PAGE_SIZE")
    @classmethod
    def _validate_github_page_size(cls, value: int) -> int:
        if not (1 <= value <= 100):
            raise ValueError("GITHUB_COLLECTION_PAGE_SIZE must be between 1 and 100")
        return value

    @field_validator("GITHUB_MAX_RETRIES")
    @classmethod
    def _validate_github_max_retries(cls, value: int) -> int:
        if not (0 <= value <= 10):
            raise ValueError("GITHUB_MAX_RETRIES must be between 0 and 10")
        return value

    @field_validator(
        "REDDIT_REQUEST_TIMEOUT_SECONDS",
        "REDDIT_MAX_RECORDS_PER_ANALYSIS",
        "REDDIT_MAX_POSTS_PER_SUBREDDIT",
        "REDDIT_DEFAULT_POSTS_PER_SUBREDDIT",
        "REDDIT_MAX_COMMENTS_PER_POST",
        "REDDIT_MAX_MORE_CHILDREN_REQUESTS",
        "REDDIT_MORE_CHILDREN_BATCH_SIZE",
        "REDDIT_MAX_COMMENT_DEPTH",
    )
    @classmethod
    def _validate_positive_reddit_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("REDDIT_LISTING_PAGE_SIZE")
    @classmethod
    def _validate_reddit_page_size(cls, value: int) -> int:
        # Reddit's own documented maximum. Sending more is silently clamped
        # by Reddit, which makes `after`-cursor pagination inconsistent with
        # what the caller believes it requested.
        if not (1 <= value <= 100):
            raise ValueError("REDDIT_LISTING_PAGE_SIZE must be between 1 and 100")
        return value

    @field_validator("REDDIT_MAX_RETRIES")
    @classmethod
    def _validate_reddit_max_retries(cls, value: int) -> int:
        if not (0 <= value <= 10):
            raise ValueError("REDDIT_MAX_RETRIES must be between 0 and 10")
        return value

    @field_validator("REDDIT_RATE_LIMIT_SLOWDOWN_THRESHOLD")
    @classmethod
    def _validate_reddit_slowdown_threshold(cls, value: float) -> float:
        if not (0.0 <= value <= 1.0):
            raise ValueError(
                "REDDIT_RATE_LIMIT_SLOWDOWN_THRESHOLD must be between 0.0 and 1.0"
            )
        return value

    @field_validator("REDDIT_USER_AGENT")
    @classmethod
    def _sanitize_reddit_user_agent(cls, value: str) -> str:
        """Strips control characters from the User-Agent.

        Same reasoning as _sanitize_github_token: this value is interpolated
        into a request header, and a trailing newline is exactly what
        copy-pasting into a .env file produces. Sanitizing rather than
        raising avoids pydantic echoing the offending input into the startup
        log.
        """
        return "".join(char for char in value if ord(char) >= 0x20).strip()

    @field_validator("REDDIT_API_BASE_URL", "REDDIT_OAUTH_TOKEN_URL")
    @classmethod
    def _validate_reddit_urls(cls, value: str, info) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"{info.field_name} must be an absolute https:// URL")
        return value.rstrip("/")

    @field_validator("GITHUB_API_BASE_URL")
    @classmethod
    def _validate_github_api_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("GITHUB_API_BASE_URL must be an absolute https:// URL")
        return value

    @model_validator(mode="after")
    def _validate_and_generate_credential_encryption_key(self) -> "Settings":
        if not self.GITHUB_CONNECTOR_ENABLED:
            return self
        is_production = self.ENVIRONMENT.lower() == "production"
        if not self.CONNECTOR_CREDENTIAL_ENCRYPTION_KEY.get_secret_value():
            if is_production:
                raise ValueError(
                    "CONNECTOR_CREDENTIAL_ENCRYPTION_KEY must be set in production when "
                    "GITHUB_CONNECTOR_ENABLED=true. Generate one with: "
                    'python -c "import secrets; print(secrets.token_urlsafe(64))"'
                )
            self.CONNECTOR_CREDENTIAL_ENCRYPTION_KEY = SecretStr(secrets.token_urlsafe(64))
            self.CONNECTOR_CREDENTIAL_ENCRYPTION_KEY_AUTO_GENERATED = True
        elif (
            len(self.CONNECTOR_CREDENTIAL_ENCRYPTION_KEY.get_secret_value())
            < _MIN_AUTH_SECRET_LENGTH
        ):
            raise ValueError(
                f"CONNECTOR_CREDENTIAL_ENCRYPTION_KEY must be at least {_MIN_AUTH_SECRET_LENGTH} "
                "characters"
            )
        return self

    @model_validator(mode="after")
    def _validate_priority_weights_sum_to_one(self) -> "Settings":
        total = (
            self.SIGNAL_PRIORITY_WEIGHT_FREQUENCY
            + self.SIGNAL_PRIORITY_WEIGHT_SEVERITY
            + self.SIGNAL_PRIORITY_WEIGHT_RECENCY
            + self.SIGNAL_PRIORITY_WEIGHT_IMPACT
            + self.SIGNAL_PRIORITY_WEIGHT_CONFIDENCE
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                "SIGNAL_PRIORITY_WEIGHT_* settings must sum to 1.0 "
                f"(currently {total:.6f}) -- adjust one or more weights"
            )
        return self

    # ---- Action Center (Sprint 19) ----
    ACTION_CENTER_ENABLED: bool = True
    ACTION_PLAN_MAX_PER_USER: int = 200
    ACTION_TASK_MAX_PER_PLAN: int = 100
    ACTION_EVENT_MAX_PAGE_SIZE: int = 100
    ACTION_REQUIRE_TASKS_COMPLETE_FOR_PLAN_COMPLETION: bool = True
    ACTION_DEFAULT_PAGE_SIZE: int = 20
    ACTION_MAX_PAGE_SIZE: int = 100
    # Bounds ActionPlanEvent.previous_values / .new_values -- oversized
    # payloads are replaced with a {"truncated": true} marker rather than
    # persisted, the same policy SOURCE_METADATA_MAX_BYTES already applies
    # to connector record metadata.
    ACTION_EVENT_VALUE_MAX_BYTES: int = 4096
    ACTION_WRITE_RATE_LIMIT_REQUESTS: int = 30
    ACTION_WRITE_RATE_LIMIT_WINDOW_SECONDS: int = 60

    @field_validator(
        "ACTION_PLAN_MAX_PER_USER",
        "ACTION_TASK_MAX_PER_PLAN",
        "ACTION_EVENT_MAX_PAGE_SIZE",
        "ACTION_DEFAULT_PAGE_SIZE",
        "ACTION_MAX_PAGE_SIZE",
        "ACTION_EVENT_VALUE_MAX_BYTES",
        "ACTION_WRITE_RATE_LIMIT_REQUESTS",
        "ACTION_WRITE_RATE_LIMIT_WINDOW_SECONDS",
    )
    @classmethod
    def _validate_positive_action_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @model_validator(mode="after")
    def _validate_action_page_size_bounds(self) -> "Settings":
        if self.ACTION_DEFAULT_PAGE_SIZE > self.ACTION_MAX_PAGE_SIZE:
            raise ValueError(
                "ACTION_DEFAULT_PAGE_SIZE must not exceed ACTION_MAX_PAGE_SIZE "
                f"({self.ACTION_MAX_PAGE_SIZE})"
            )
        return self

    # ---- Trend intelligence (Sprint 20) ----
    TREND_INTELLIGENCE_ENABLED: bool = True
    # Minimum blended similarity score (signal type match is a hard
    # prerequisite, this threshold applies on top of it) for two signals
    # from different jobs to be considered "the same" signal -- see
    # app/services/trends/matching.py.
    TREND_MATCH_THRESHOLD: float = 0.45
    TREND_MIN_RECORDS_PER_JOB: int = 5
    # Combined (baseline + comparison) frequency below this is reported as
    # insufficient_data rather than a directional trend -- too small a
    # sample to say anything meaningful either way.
    TREND_MIN_SIGNAL_COUNT: int = 2
    # All three *_THRESHOLD/_TOLERANCE settings are percentages (0-100)
    # applied to the RELATIVE change in a signal's frequency ratio
    # (frequency_count / job.comments_analyzed), never a raw count -- so a
    # signal is judged against jobs of different sizes fairly.
    TREND_STABLE_CHANGE_TOLERANCE: float = 15.0
    TREND_RISING_THRESHOLD: float = 25.0
    TREND_FALLING_THRESHOLD: float = 25.0
    TREND_DEFAULT_WINDOW_DAYS: int = 30
    TREND_MAX_WINDOW_DAYS: int = 365
    TREND_MAX_SIGNALS_PER_COMPARISON: int = 200
    TREND_OUTCOME_MIN_POST_ACTION_RECORDS: int = 3
    TREND_ALGORITHM_VERSION: str = "v1"
    TREND_DEFAULT_PAGE_SIZE: int = 20
    TREND_MAX_PAGE_SIZE: int = 100
    TREND_WRITE_RATE_LIMIT_REQUESTS: int = 20
    TREND_WRITE_RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ---- Trend AI enrichment (Sprint 20) ----
    # Same pattern as SIGNAL_PROVIDER_* (Sprint 17): bounded batch/evidence/
    # excerpt limits for the optional narrative-only provider call. Reuses
    # INSIGHT_AI_PRIMARY_PROVIDER/_FALLBACK_PROVIDER and the Gemini/OpenAI
    # keys+models already configured for insights/signals -- no new secret.
    TREND_PROVIDER_ENRICHMENT_ENABLED: bool = True
    TREND_PROVIDER_TIMEOUT_SECONDS: int = 30
    TREND_PROVIDER_MAX_RETRIES: int = 1
    TREND_PROVIDER_MAX_EVIDENCE_EXCERPTS: int = 5
    TREND_PROVIDER_MAX_EXCERPT_CHARS: int = 200

    @field_validator(
        "TREND_MIN_RECORDS_PER_JOB",
        "TREND_MIN_SIGNAL_COUNT",
        "TREND_DEFAULT_WINDOW_DAYS",
        "TREND_MAX_WINDOW_DAYS",
        "TREND_MAX_SIGNALS_PER_COMPARISON",
        "TREND_OUTCOME_MIN_POST_ACTION_RECORDS",
        "TREND_DEFAULT_PAGE_SIZE",
        "TREND_MAX_PAGE_SIZE",
        "TREND_WRITE_RATE_LIMIT_REQUESTS",
        "TREND_WRITE_RATE_LIMIT_WINDOW_SECONDS",
        "TREND_PROVIDER_TIMEOUT_SECONDS",
        "TREND_PROVIDER_MAX_EVIDENCE_EXCERPTS",
        "TREND_PROVIDER_MAX_EXCERPT_CHARS",
    )
    @classmethod
    def _validate_positive_trend_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("TREND_PROVIDER_MAX_RETRIES")
    @classmethod
    def _validate_trend_max_retries(cls, value: int) -> int:
        if not (0 <= value <= 10):
            raise ValueError("TREND_PROVIDER_MAX_RETRIES must be between 0 and 10")
        return value

    @field_validator("TREND_MATCH_THRESHOLD")
    @classmethod
    def _validate_trend_match_threshold(cls, value: float) -> float:
        if not (0.0 <= value <= 1.0):
            raise ValueError("TREND_MATCH_THRESHOLD must be between 0.0 and 1.0")
        return value

    @field_validator(
        "TREND_STABLE_CHANGE_TOLERANCE", "TREND_RISING_THRESHOLD", "TREND_FALLING_THRESHOLD"
    )
    @classmethod
    def _validate_trend_percentage(cls, value: float, info) -> float:
        if not (0.0 <= value <= 1000.0):
            raise ValueError(f"{info.field_name} must be between 0.0 and 1000.0")
        return value

    @model_validator(mode="after")
    def _validate_trend_threshold_ordering(self) -> "Settings":
        if self.TREND_RISING_THRESHOLD < self.TREND_STABLE_CHANGE_TOLERANCE:
            raise ValueError("TREND_RISING_THRESHOLD must be >= TREND_STABLE_CHANGE_TOLERANCE")
        if self.TREND_FALLING_THRESHOLD < self.TREND_STABLE_CHANGE_TOLERANCE:
            raise ValueError("TREND_FALLING_THRESHOLD must be >= TREND_STABLE_CHANGE_TOLERANCE")
        return self

    @model_validator(mode="after")
    def _validate_trend_page_size_bounds(self) -> "Settings":
        if self.TREND_DEFAULT_PAGE_SIZE > self.TREND_MAX_PAGE_SIZE:
            raise ValueError(
                "TREND_DEFAULT_PAGE_SIZE must not exceed TREND_MAX_PAGE_SIZE "
                f"({self.TREND_MAX_PAGE_SIZE})"
            )
        return self

    @model_validator(mode="after")
    def _validate_trend_window_bounds(self) -> "Settings":
        if self.TREND_DEFAULT_WINDOW_DAYS > self.TREND_MAX_WINDOW_DAYS:
            raise ValueError(
                "TREND_DEFAULT_WINDOW_DAYS must not exceed TREND_MAX_WINDOW_DAYS "
                f"({self.TREND_MAX_WINDOW_DAYS})"
            )
        return self

    # ---- Ask Your Data (Sprint 21) ----
    ASK_DATA_ENABLED: bool = True
    ASK_DATA_MAX_QUESTION_LENGTH: int = 1000
    ASK_DATA_MAX_CONTEXT_ITEMS: int = 50
    ASK_DATA_MAX_EVIDENCE_EXCERPTS: int = 20
    ASK_DATA_MAX_EXCERPT_CHARS: int = 200
    # TTL for the Redis-backed answer cache (app/services/query/cache.py) --
    # short by design so a re-run job/newer signal is reflected soon rather
    # than serving an indefinitely stale grounded answer. No raw question
    # text is ever persisted to Postgres -- see that module's docstring.
    ASK_DATA_CACHE_TTL_SECONDS: int = 900
    ASK_DATA_WRITE_RATE_LIMIT_REQUESTS: int = 20
    ASK_DATA_WRITE_RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ---- Ask Your Data provider mode (Sprint 21) ----
    # Reuses INSIGHT_AI_PRIMARY_PROVIDER/_FALLBACK_PROVIDER and the existing
    # Gemini/OpenAI keys+models -- no new secret. Also used by Reports
    # (Sprint 21) for its own optional narrative enrichment, since both
    # features are the same "narrate already-computed data" shape.
    ASK_DATA_PROVIDER_ENABLED: bool = True
    ASK_DATA_PROVIDER_TIMEOUT_SECONDS: int = 30
    ASK_DATA_PROVIDER_MAX_RETRIES: int = 1

    # ---- Global AI Assistant (Phase 3) ----
    # Reuses INSIGHT_AI_PRIMARY_PROVIDER/_FALLBACK_PROVIDER and the existing
    # GEMINI_API_KEY/OPENAI_API_KEY/INSIGHT_AI_*_MODEL settings -- a genuine
    # tool-calling loop, not a rephrase-only call like Ask Your Data's
    # provider, so it gets its own timeout/retry knobs tuned for a
    # multi-round conversation rather than a single-shot rephrase.
    ASSISTANT_ENABLED: bool = True
    ASSISTANT_HISTORY_LIMIT: int = 20
    ASSISTANT_PROVIDER_TIMEOUT_SECONDS: int = 45
    ASSISTANT_PROVIDER_MAX_RETRIES: int = 1
    ASSISTANT_SEND_RATE_LIMIT_REQUESTS: int = 15
    ASSISTANT_SEND_RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ---- Reports (Sprint 21) ----
    REPORTS_ENABLED: bool = True
    REPORT_MAX_PER_USER: int = 200
    REPORT_MAX_SECTIONS: int = 20
    REPORT_ALGORITHM_VERSION: str = "v1"
    REPORT_DEFAULT_PAGE_SIZE: int = 20
    REPORT_MAX_PAGE_SIZE: int = 100
    REPORT_WRITE_RATE_LIMIT_REQUESTS: int = 10
    REPORT_WRITE_RATE_LIMIT_WINDOW_SECONDS: int = 60

    @field_validator(
        "ASK_DATA_MAX_QUESTION_LENGTH",
        "ASK_DATA_MAX_CONTEXT_ITEMS",
        "ASK_DATA_MAX_EVIDENCE_EXCERPTS",
        "ASK_DATA_MAX_EXCERPT_CHARS",
        "ASK_DATA_CACHE_TTL_SECONDS",
        "ASK_DATA_WRITE_RATE_LIMIT_REQUESTS",
        "ASK_DATA_WRITE_RATE_LIMIT_WINDOW_SECONDS",
        "ASK_DATA_PROVIDER_TIMEOUT_SECONDS",
        "REPORT_MAX_PER_USER",
        "REPORT_MAX_SECTIONS",
        "REPORT_DEFAULT_PAGE_SIZE",
        "REPORT_MAX_PAGE_SIZE",
        "REPORT_WRITE_RATE_LIMIT_REQUESTS",
        "REPORT_WRITE_RATE_LIMIT_WINDOW_SECONDS",
    )
    @classmethod
    def _validate_positive_ask_data_report_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("ASK_DATA_PROVIDER_MAX_RETRIES")
    @classmethod
    def _validate_ask_data_max_retries(cls, value: int) -> int:
        if not (0 <= value <= 10):
            raise ValueError("ASK_DATA_PROVIDER_MAX_RETRIES must be between 0 and 10")
        return value

    @model_validator(mode="after")
    def _validate_report_page_size_bounds(self) -> "Settings":
        if self.REPORT_DEFAULT_PAGE_SIZE > self.REPORT_MAX_PAGE_SIZE:
            raise ValueError(
                "REPORT_DEFAULT_PAGE_SIZE must not exceed REPORT_MAX_PAGE_SIZE "
                f"({self.REPORT_MAX_PAGE_SIZE})"
            )
        return self

    # ---- Report export (Sprint 22) ----
    REPORT_EXPORT_STORAGE_PATH: str = "var/report_exports"
    REPORT_EXPORT_MAX_FILE_MB: int = 20
    REPORT_EXPORT_RETENTION_DAYS: int = 30

    @field_validator("REPORT_EXPORT_MAX_FILE_MB", "REPORT_EXPORT_RETENTION_DAYS")
    @classmethod
    def _validate_positive_report_export_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @model_validator(mode="after")
    def _validate_report_export_storage_path(self) -> "Settings":
        if not self.REPORT_EXPORT_STORAGE_PATH.strip():
            raise ValueError("REPORT_EXPORT_STORAGE_PATH must not be blank")
        return self

    # ---- Universal source foundation (Sprint 23) ----
    # SOURCE_METADATA_MAX_BYTES already exists in the Multi-source domain
    # (Sprint 15) block above and is reused as-is for paste-text records.
    SOURCE_INPUT_MAX_LENGTH: int = 50_000
    SOURCE_TEXT_MAX_RECORDS: int = 500
    SOURCE_TEXT_MAX_RECORD_LENGTH: int = 5_000

    @field_validator(
        "SOURCE_INPUT_MAX_LENGTH", "SOURCE_TEXT_MAX_RECORDS", "SOURCE_TEXT_MAX_RECORD_LENGTH"
    )
    @classmethod
    def _validate_positive_source_foundation_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    # ---- Account self-service: display-name cooldown, delete-account, contact ----
    ACCOUNT_DISPLAY_NAME_COOLDOWN_DAYS: int = 60
    ACCOUNT_DELETE_RATE_LIMIT_REQUESTS: int = 5
    ACCOUNT_DELETE_RATE_LIMIT_WINDOW_SECONDS: int = 3600
    # Operator inbox the real Contact form (already built on the landing
    # page) delivers to via the existing SMTP/outbox infrastructure. Unset
    # by default -- the submission is still always durably stored even
    # when this is unset, only the notification email is skipped.
    CONTACT_INBOX_EMAIL: str | None = None
    CONTACT_RATE_LIMIT_REQUESTS: int = 5
    CONTACT_RATE_LIMIT_WINDOW_SECONDS: int = 3600

    @field_validator(
        "ACCOUNT_DISPLAY_NAME_COOLDOWN_DAYS",
        "ACCOUNT_DELETE_RATE_LIMIT_REQUESTS",
        "ACCOUNT_DELETE_RATE_LIMIT_WINDOW_SECONDS",
        "CONTACT_RATE_LIMIT_REQUESTS",
        "CONTACT_RATE_LIMIT_WINDOW_SECONDS",
    )
    @classmethod
    def _validate_positive_account_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    # ---- Billing: Stripe (Phase 3) ----
    # All unset by default -- `billing_configured` below is the single
    # source of truth for whether any billing UI/endpoint should render as
    # usable; nothing here is ever treated as configured just because a
    # field has a non-empty default; there are no defaults.
    STRIPE_SECRET_KEY: SecretStr = SecretStr("")
    STRIPE_PRICE_ID_PRO: str = ""
    STRIPE_WEBHOOK_SECRET: SecretStr = SecretStr("")
    STRIPE_SUCCESS_URL: str = ""
    STRIPE_CANCEL_URL: str = ""

    # Pro-tier usage limits -- the Free-tier equivalents are
    # USAGE_MAX_ACTIVE_ANALYSIS_JOBS_PER_USER / USAGE_MAX_ANALYSIS_JOBS_PER_DAY /
    # USAGE_MAX_COMMENT_LIMIT_PER_JOB above (Sprint 13). See
    # app/services/billing/limits.py::resolve_limits, the one place either
    # tier's values are actually looked up.
    USAGE_MAX_ACTIVE_ANALYSIS_JOBS_PER_USER_PRO: int = 10
    USAGE_MAX_ANALYSIS_JOBS_PER_DAY_PRO: int = 100
    USAGE_MAX_COMMENT_LIMIT_PER_JOB_PRO: int = 5000

    @property
    def billing_configured(self) -> bool:
        return bool(
            self.STRIPE_SECRET_KEY.get_secret_value()
            and self.STRIPE_PRICE_ID_PRO
            and self.STRIPE_WEBHOOK_SECRET.get_secret_value()
        )

    @field_validator(
        "USAGE_MAX_ACTIVE_ANALYSIS_JOBS_PER_USER_PRO",
        "USAGE_MAX_ANALYSIS_JOBS_PER_DAY_PRO",
        "USAGE_MAX_COMMENT_LIMIT_PER_JOB_PRO",
    )
    @classmethod
    def _validate_positive_billing_int(cls, value: int, info) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @model_validator(mode="after")
    def _validate_pro_usage_limits_within_global_limits(self) -> "Settings":
        if self.USAGE_MAX_COMMENT_LIMIT_PER_JOB_PRO > self.ANALYSIS_MAX_COMMENT_LIMIT:
            raise ValueError(
                "USAGE_MAX_COMMENT_LIMIT_PER_JOB_PRO must not exceed ANALYSIS_MAX_COMMENT_LIMIT "
                f"({self.ANALYSIS_MAX_COMMENT_LIMIT})"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
