"""Dataset insight synthesis: AI when a provider is available, deterministic
evidence ranking when it is not.

The AI path reuses the product's existing provider abstraction end to end --
`AIInsightService`, `ProviderRegistry`, the retry/fallback ladder and the
timeout budget are all the ones every other capability uses. No new provider,
no new client, no new credentials.

What is NOT reused is the output contract. Feedback validation checks cluster
ids and sentiment confidence levels, which do not exist here. This module
validates the one thing that matters for a dataset: every insight cites at
least one REAL fact id, and an insight citing an invented one is discarded.
An insight with no surviving citation is dropped entirely rather than shown
without evidence.

The fallback is not a placeholder. It renders the top-weighted facts
(app/datasets/evidence.py) as insights with their real numbers, so a
deployment with no LLM configured still gets specific, measured findings --
just without the synthesis across them.
"""

import logging
import re
from dataclasses import dataclass

from app.datasets.evidence import (
    FACT_CATEGORY_ANOMALY,
    FACT_CATEGORY_DISTRIBUTION,
    FACT_CATEGORY_QUALITY,
    FACT_CATEGORY_RELATIONSHIP,
    FACT_CATEGORY_SEGMENT,
    FACT_CATEGORY_STRUCTURE,
    FACT_CATEGORY_TEXT,
    FACT_CATEGORY_TREND,
    FACT_SCOPE_ANOMALY,
    FACT_SCOPE_QUALITY,
    FACT_SCOPE_RELATIONSHIP,
    FACT_SCOPE_SEGMENT,
    FACT_SCOPE_TREND,
    MAX_FACTS_FOR_AI,
    DatasetFact,
)
from app.datasets.prompts import (
    CONFIDENCE_LEVELS,
    DATASET_PROMPT_VERSION,
    INSIGHT_TYPES,
    MAX_INSIGHTS,
    MIN_INSIGHTS,
)
from app.datasets.profiling import ColumnProfile
from app.datasets.quality import (
    QualityReport,
    canonicalize_health_band_text,
    health_band_label,
)

logger = logging.getLogger(__name__)

DATASET_INSIGHTS_CAPABILITY = "dataset_intelligence"

_TITLE_MAX = 140
_TEXT_MAX = 600

# Interpretations the analysis cannot support, checked on generated text.
#
# A neutral sentiment label means the classifier found no clear positive or
# negative signal. It is NOT a measure of engagement, interest or attention,
# and this product has no engagement data for a spreadsheet column at all --
# so a sentence like "mostly neutral, suggesting limited engagement" invents
# a finding. Observed verbatim from a local model before this guard existed.
_BANNED_INTERPRETATIONS = (
    "low engagement",
    "limited engagement",
    "lack of engagement",
    "lack of audience engagement",
    "weak engagement",
    "little engagement",
    "poor engagement",
    "weak interest",
    "low interest",
    "lack of interest",
    "limited interest",
    "disengaged",
    "apathy",
    "apathetic",
    "indifference",
)

# Concepts this engine never measures; a sentence asserting one is invented.
_UNMEASURED_CONCEPT = re.compile(
    r"\b(?:dis)?engag(?:e|ed|es|ement|ing)\b"
    r"|\binterest(?:ed)?\b"
    r"|\bapath(?:y|etic)\b"
    r"|\bindifferen(?:ce|t)\b"
    r"|\bmotivat(?:ion|ed)\b"
    r"|\battention\s+spans?\b"
    r"|\bprevalence\b"
    r"|\bdiagnos(?:is|es|ed)\b",
    re.IGNORECASE,
)


def _contains_banned_interpretation(*texts: str | None, measured: str = "") -> str | None:
    """The matched concept, or None. A concept named in `measured` is allowed."""
    haystack = measured.lower()
    for text in texts:
        if not text:
            continue
        match = _UNMEASURED_CONCEPT.search(text)
        if match is None:
            continue
        if haystack and match.group(0).lower() in haystack:
            continue
        return match.group(0).lower()
    return None


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def scrub_unsupported_sentences(text: str | None, measured: str = "") -> str:
    """Drops stored sentences asserting something the analysis never measured."""
    if not text:
        return text or ""
    sentences = _SENTENCE_SPLIT.split(text)
    kept = [
        sentence
        for sentence in sentences
        if _contains_banned_interpretation(sentence, measured=measured) is None
    ]
    if not kept:
        return ""
    return " ".join(kept).strip()


def evidence_vocabulary(facts: list[DatasetFact], columns: list[str] | None = None) -> str:
    """Everything the analysis measured, as one lowercased blob."""
    parts = [fact.statement for fact in facts]
    parts.extend(name for name in (columns or []) if name)
    for fact in facts:
        parts.extend(str(column) for column in fact.columns if column)
    return " ".join(parts).lower()


@dataclass(frozen=True)
class DatasetInsight:
    insight_type: str
    title: str
    explanation: str
    evidence: str
    evidence_fact_ids: list[str]
    impact: str
    recommended_action: str | None
    confidence: str
    generated_by: str


@dataclass(frozen=True)
class ExecutiveSummary:
    scope: str
    data_health: str
    strongest_findings: list[str]
    key_risks: list[str]
    recommended_actions: list[str]
    generated_by: str


@dataclass(frozen=True)
class DatasetInsightResult:
    insights: list[DatasetInsight]
    executive_summary: ExecutiveSummary
    generated_by: str
    provider_status: str
    provider_used: str | None
    model_used: str | None
    prompt_version: str
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class DatasetInsightSelection:
    """Exactly what the provider is shown. Bounded on purpose: the facts are
    already the distilled form of the analysis, so the prompt carries a
    summary and a fact list rather than the dataset."""

    dataset_summary: dict
    coverage: dict
    columns: list[dict]
    facts: list[DatasetFact]


def build_selection(
    dataset_summary: dict,
    coverage: dict,
    profiles: list[ColumnProfile],
    facts: list[DatasetFact],
) -> DatasetInsightSelection:
    return DatasetInsightSelection(
        dataset_summary=dataset_summary,
        coverage=coverage,
        columns=[
            {
                "name": profile.name,
                "type": profile.technical_type.value,
                "role": profile.semantic_role.value,
                "missing_percentage": profile.null_percentage,
                "unique_count": profile.unique_count,
            }
            for profile in profiles
        ],
        facts=facts[:MAX_FACTS_FOR_AI],
    )


class DatasetOutputError(Exception):
    pass


def _clean(value, limit: int) -> str:
    if not isinstance(value, str):
        raise DatasetOutputError("Expected a string field")
    text = value.strip()
    if not text:
        raise DatasetOutputError("Empty string field")
    return text[:limit]


def validate_dataset_output(
    raw: dict, valid_fact_ids: set[str], measured: str = ""
) -> tuple[list[DatasetInsight], ExecutiveSummary | None]:
    """Rejects anything that is not grounded in a supplied fact.

    Per-insight rather than all-or-nothing: a provider that returns five good
    insights and one hallucinated citation should cost the user the bad one,
    not all six. If nothing survives, the caller falls back to the
    deterministic path.
    """
    if not isinstance(raw, dict):
        raise DatasetOutputError("Response is not a JSON object")

    raw_insights = raw.get("insights")
    if not isinstance(raw_insights, list) or not raw_insights:
        raise DatasetOutputError("Response contains no insights array")

    insights: list[DatasetInsight] = []
    for entry in raw_insights:
        if not isinstance(entry, dict):
            continue
        fact_ids = entry.get("evidence_fact_ids")
        if not isinstance(fact_ids, list):
            continue
        cited = [str(fact_id) for fact_id in fact_ids if str(fact_id) in valid_fact_ids]
        if not cited:
            logger.info(
                "dataset_insight_rejected_ungrounded",
                extra={"cited": str(fact_ids)[:200]},
            )
            continue
        insight_type = entry.get("type")
        if insight_type not in INSIGHT_TYPES:
            insight_type = "key_finding"
        confidence = entry.get("confidence")
        if confidence not in CONFIDENCE_LEVELS:
            confidence = "medium"
        try:
            insight = DatasetInsight(
                insight_type=insight_type,
                title=_clean(entry.get("title"), _TITLE_MAX),
                explanation=_clean(entry.get("explanation"), _TEXT_MAX),
                evidence=_clean(entry.get("evidence"), _TEXT_MAX),
                evidence_fact_ids=cited,
                impact=_clean(entry.get("impact"), _TEXT_MAX),
                recommended_action=(
                    _clean(entry.get("recommended_action"), _TEXT_MAX)
                    if isinstance(entry.get("recommended_action"), str)
                    and entry.get("recommended_action").strip()
                    else None
                ),
                confidence=confidence,
                generated_by="ai",
            )
        except DatasetOutputError:
            continue
        banned = _contains_banned_interpretation(
            insight.title,
            insight.explanation,
            insight.impact,
            insight.recommended_action,
            measured=measured,
        )
        if banned is not None:
            # Dropped, not rewritten. The claim is not supported by anything
            # the engine measured, and silently editing it would leave the
            # rest of the insight resting on the same reasoning.
            logger.info("dataset_insight_rejected_unsupported_claim", extra={"phrase": banned})
            continue

        insights.append(insight)
        if len(insights) >= MAX_INSIGHTS:
            break

    if not insights:
        raise DatasetOutputError("No insight in the response cited a real fact")

    summary = None
    raw_summary = raw.get("executive_summary")
    if isinstance(raw_summary, dict) and not _contains_banned_interpretation(
        raw_summary.get("scope") if isinstance(raw_summary.get("scope"), str) else None,
        (
            raw_summary.get("data_health")
            if isinstance(raw_summary.get("data_health"), str)
            else None
        ),
        *[item for item in _string_list(raw_summary.get("strongest_findings"))],
        *[item for item in _string_list(raw_summary.get("recommended_actions"))],
        *[item for item in _string_list(raw_summary.get("key_risks"))],
        measured=measured,
    ):
        try:
            summary = ExecutiveSummary(
                scope=_clean(raw_summary.get("scope"), _TEXT_MAX),
                data_health=_clean(raw_summary.get("data_health"), _TEXT_MAX),
                strongest_findings=_string_list(raw_summary.get("strongest_findings")),
                key_risks=_string_list(raw_summary.get("key_risks")),
                recommended_actions=_string_list(raw_summary.get("recommended_actions")),
                generated_by="ai",
            )
        except DatasetOutputError:
            summary = None

    return insights, summary


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip()[:_TEXT_MAX] for item in value if isinstance(item, str) and item.strip()][
        :4
    ]


_SCOPE_TO_TYPE = {
    FACT_SCOPE_QUALITY: "data_quality_risk",
    FACT_SCOPE_RELATIONSHIP: "relationship",
    FACT_SCOPE_SEGMENT: "segment_difference",
    FACT_SCOPE_TREND: "trend",
    FACT_SCOPE_ANOMALY: "anomaly",
}

_IMPACT_BY_TYPE = {
    "data_quality_risk": "Any figure computed from the affected column inherits this problem.",
    "relationship": "The two columns move together; treating either as independent of the other "
    "would be misleading.",
    "segment_difference": "The overall average hides this gap between groups.",
    "trend": "The direction of travel matters more than the current level on its own.",
    "anomaly": "These rows sit far outside the normal range and should be confirmed before they "
    "are included in an average.",
    "key_finding": "This shapes what the dataset can and cannot be used to answer.",
}


def build_fallback_insights(
    facts: list[DatasetFact], quality: QualityReport
) -> list[DatasetInsight]:
    """Deterministic insights, from the highest-weighted facts.

    Deliberately spread across scopes: taking the top N by weight alone
    frequently returns four quality issues and nothing else, which is a
    truthful but useless reading of a dataset.
    """
    # Two passes, both de-duplicated BY TITLE.
    #
    # Scope diversity first, because taking the top N by weight alone
    # routinely returns four quality issues and nothing else -- a truthful
    # but useless reading of a dataset. Then top up by weight.
    #
    # The title check is what stops two facts about the same column
    # rendering as the same headline twice: their titles are built from the
    # columns they cite, so two facts about `feedback` both title as "Key
    # finding: feedback" and read as one insight repeated.
    chosen: list[DatasetFact] = []
    seen_scopes: set[str] = set()
    used_titles: set[str] = set()

    def _take(fact: DatasetFact) -> bool:
        title = _fallback_title(fact, _SCOPE_TO_TYPE.get(fact.scope, "key_finding"))
        if title in used_titles:
            return False
        used_titles.add(title)
        chosen.append(fact)
        return True

    # Context facts are excluded from BOTH passes: an "insight" restating
    # the row count or the health score printed at the top of the same page
    # is a repeat, not a finding.
    candidates = [fact for fact in facts if not fact.context_only]

    for fact in candidates:
        if fact.scope in seen_scopes:
            continue
        if _take(fact):
            seen_scopes.add(fact.scope)
        if len(chosen) >= MIN_INSIGHTS + 1:
            break
    for fact in candidates:
        if len(chosen) >= MAX_INSIGHTS:
            break
        if fact not in chosen:
            _take(fact)

    insights: list[DatasetInsight] = []
    for fact in chosen:
        insight_type = _SCOPE_TO_TYPE.get(fact.scope, "key_finding")
        recommendation = None
        if insight_type == "data_quality_risk":
            matching = next(
                (issue for issue in quality.issues if issue.explanation == fact.statement),
                None,
            )
            recommendation = matching.recommendation if matching else None
        insights.append(
            DatasetInsight(
                insight_type=insight_type,
                title=_fallback_title(fact, insight_type),
                explanation=fact.statement,
                evidence=fact.statement,
                evidence_fact_ids=[fact.fact_id],
                impact=_IMPACT_BY_TYPE.get(insight_type, _IMPACT_BY_TYPE["key_finding"]),
                recommended_action=recommendation,
                confidence="high",
                generated_by="deterministic",
            )
        )
    return insights


def _fallback_title(fact: DatasetFact, insight_type: str) -> str:
    if fact.columns:
        subject = ", ".join(name for name in fact.columns if name)[:60]
    else:
        subject = "This dataset"
    labels = {
        "data_quality_risk": f"Data quality risk in {subject}",
        "relationship": f"Relationship between {subject}",
        "segment_difference": f"Segments differ in {subject}",
        "trend": f"Trend in {subject}",
        "anomaly": f"Unusual values in {subject}",
        "key_finding": f"Key finding: {subject}",
    }
    return labels.get(insight_type, labels["key_finding"])[:_TITLE_MAX]


# Health is absent on purpose: it is already the summary's second line.
_SUMMARY_CATEGORY_ORDER = (
    FACT_CATEGORY_STRUCTURE,
    FACT_CATEGORY_QUALITY,
    FACT_CATEGORY_TEXT,
    FACT_CATEGORY_TREND,
    FACT_CATEGORY_RELATIONSHIP,
    FACT_CATEGORY_SEGMENT,
    FACT_CATEGORY_DISTRIBUTION,
    FACT_CATEGORY_ANOMALY,
)

_MAX_SUMMARY_HIGHLIGHTS = 5


def build_summary_highlights(facts: list[DatasetFact]) -> list[str]:
    """One measured statement per category, verbatim, in a fixed order."""
    by_category: dict[str, str] = {}
    for fact in facts:
        if fact.category and fact.category not in by_category and fact.statement:
            by_category[fact.category] = fact.statement
    highlights = [
        by_category[category] for category in _SUMMARY_CATEGORY_ORDER if category in by_category
    ]
    return highlights[:_MAX_SUMMARY_HIGHLIGHTS]


def _deterministic_actions(
    quality: QualityReport, coverage: dict | None, facts: list[DatasetFact] | None = None
) -> list[str]:
    """Next steps naming what to inspect, why, and what the answer decides."""
    actions: list[str] = []
    concentration = quality.missing_concentration

    if concentration is not None and concentration.empty_columns:
        names = ", ".join(f"'{name}'" for name in concentration.empty_columns[:5])
        count = len(concentration.empty_columns)
        recovery = (
            f" Removing them would raise the health score to "
            f"{quality.projected_health_score}/100."
            if quality.projected_health_score is not None
            else ""
        )
        actions.append(
            f"Verify whether {names} {'was' if count == 1 else 'were'} expected to be populated "
            f"by the source or export -- {'this column holds' if count == 1 else 'these columns hold'} "
            f"no values at all. If the field is permanently unused, drop it from the dataset."
            + recovery
        )

    if quality.duplicate_rows > 0:
        actions.append(
            f"De-duplicate the {quality.duplicate_rows:,} repeated row(s) before computing any "
            "count, sum or average -- each is currently counted more than once, so every "
            "aggregate is overstated by an unknown amount."
        )

    for fact in facts or []:
        if fact.scope != FACT_SCOPE_TREND:
            continue
        change = fact.measures.get("period_over_period_percentage")
        if not isinstance(change, (int, float)) or abs(change) < 25:
            continue
        column = (fact.columns or [""])[0]
        actions.append(
            f"Check the collection or export process around the point where row volume changes "
            f"({change:+.1f}% between the two halves of '{column}') to establish whether this "
            "reflects a real change in activity or an incomplete extract. The answer decides "
            "whether the trend is a finding or an artefact."
        )
        break

    # Sampled text coverage is an actionable limitation, not a defect.
    for area in (coverage or {}).get("areas", []):
        if area.get("area") == "text" and area.get("status") == "sampled":
            actions.append(
                f"Raise text-analysis coverage above the current "
                f"{area.get('coverage_percentage', 0):.0f}% before quoting sentiment shares as "
                "dataset-wide figures -- the present percentages describe the analyzed sample."
            )
            break

    for issue in quality.issues:
        if len(actions) >= 4:
            break
        if issue.severity.value in ("critical", "high") and issue.issue_type.value not in (
            "empty_column",
            "duplicate_rows",
        ):
            actions.append(issue.recommendation)

    return actions[:4]


def build_fallback_summary(
    dataset_summary: dict,
    quality: QualityReport,
    insights: list[DatasetInsight],
    coverage: dict | None = None,
    facts: list[DatasetFact] | None = None,
) -> ExecutiveSummary:
    risks = [
        issue.explanation
        for issue in quality.issues
        if issue.severity.value in ("critical", "high")
    ][:3]
    actions = _deterministic_actions(quality, coverage, facts)
    highlights = build_summary_highlights(facts or [])
    return ExecutiveSummary(
        scope=(
            f"{dataset_summary.get('row_count', 0):,} rows across "
            f"{dataset_summary.get('column_count', 0)} columns, uploaded as "
            f"{dataset_summary.get('file_name', 'a file')}."
        ),
        data_health=(
            f"The dataset has a health score of {quality.health_score}/100 "
            f"({health_band_label(quality.health_score)}); "
            f"{quality.missing_percentage:.1f}% of cells are empty and "
            f"{quality.duplicate_rows:,} duplicate rows were found."
        ),
        strongest_findings=highlights or [insight.explanation for insight in insights[:3]],
        key_risks=risks,
        recommended_actions=actions
        or ["No high-severity data quality problems were detected in this dataset."],
        generated_by="deterministic",
    )


def generate_dataset_insights(
    selection: DatasetInsightSelection,
    quality: QualityReport,
    ai_service,
    output_language: str = "en",
) -> DatasetInsightResult:
    """One bounded provider call, then validation, then fallback.

    Cost does not scale with dataset size: the provider sees a fixed-size
    fact list regardless of whether the file had 500 rows or 500,000.
    """
    facts = selection.facts
    fallback_insights = build_fallback_insights(facts, quality)
    fallback_summary = build_fallback_summary(
        selection.dataset_summary, quality, fallback_insights, selection.coverage, facts
    )

    if ai_service is None:
        return DatasetInsightResult(
            insights=fallback_insights,
            executive_summary=fallback_summary,
            generated_by="deterministic",
            provider_status="disabled",
            provider_used=None,
            model_used=None,
            prompt_version=DATASET_PROMPT_VERSION,
            unavailable_reason="AI insight generation is disabled for this deployment.",
        )

    from app.services.insights.ai.interfaces import CoverageSummary, InsightEvidencePackage

    package = InsightEvidencePackage(
        capability=DATASET_INSIGHTS_CAPABILITY,
        output_language=output_language,
        coverage=CoverageSummary(
            requested_comment_limit=selection.coverage.get("total_rows", 0),
            collected_comments=selection.coverage.get("total_rows", 0),
            analyzed_comments=selection.coverage.get("analyzed_rows", 0),
            clean_comments=selection.coverage.get("analyzed_rows", 0),
            collection_complete=not selection.coverage.get("sampled", False),
            coverage_percentage=selection.coverage.get("coverage_percentage", 100.0),
        ),
        local_overview_summary="",
        clusters=[],
        prompt_version=DATASET_PROMPT_VERSION,
        analysis_stage="synthesis",
        dataset_selection=selection,
    )

    try:
        outcome = ai_service.generate(package)
    except Exception:  # noqa: BLE001 -- an AI outage must never fail the analysis
        logger.warning("dataset_insight_provider_failed", exc_info=True)
        return DatasetInsightResult(
            insights=fallback_insights,
            executive_summary=fallback_summary,
            generated_by="deterministic",
            provider_status="provider_error",
            provider_used=None,
            model_used=None,
            prompt_version=DATASET_PROMPT_VERSION,
            unavailable_reason="The AI provider could not be reached; findings below are computed "
            "directly from the dataset.",
        )

    if outcome.result_json is None:
        return DatasetInsightResult(
            insights=fallback_insights,
            executive_summary=fallback_summary,
            generated_by="deterministic",
            provider_status=outcome.status,
            provider_used=outcome.provider_used,
            model_used=outcome.model_used,
            prompt_version=DATASET_PROMPT_VERSION,
            unavailable_reason=(
                "No AI provider was available; findings below are computed directly from the "
                "dataset."
            ),
        )

    valid_ids = {fact.fact_id for fact in facts}
    measured = evidence_vocabulary(
        facts, [str(column.get("name", "")) for column in selection.columns]
    )
    try:
        insights, summary = validate_dataset_output(outcome.result_json, valid_ids, measured)
    except DatasetOutputError as error:
        logger.warning("dataset_insight_output_rejected", extra={"reason": str(error)[:200]})
        return DatasetInsightResult(
            insights=fallback_insights,
            executive_summary=fallback_summary,
            generated_by="deterministic",
            provider_status="schema_validation_failed",
            provider_used=outcome.provider_used,
            model_used=outcome.model_used,
            prompt_version=DATASET_PROMPT_VERSION,
            unavailable_reason=(
                "The AI response could not be grounded in the measured evidence and was "
                "discarded; findings below are computed directly from the dataset."
            ),
        )

    if summary is not None:
        summary = ExecutiveSummary(
            scope=summary.scope,
            data_health=canonicalize_health_band_text(summary.data_health),
            strongest_findings=build_summary_highlights(facts) or summary.strongest_findings,
            key_risks=[canonicalize_health_band_text(risk) for risk in summary.key_risks],
            recommended_actions=_deterministic_actions(quality, selection.coverage, facts)
            or summary.recommended_actions,
            generated_by=summary.generated_by,
        )

    return DatasetInsightResult(
        insights=insights,
        executive_summary=summary or fallback_summary,
        generated_by="ai",
        provider_status=outcome.status,
        provider_used=outcome.provider_used,
        model_used=outcome.model_used,
        prompt_version=DATASET_PROMPT_VERSION,
    )
