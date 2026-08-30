"""Regressions for the final Overview / Data Quality refinement pass."""

from dataclasses import replace

import pytest

from app.datasets.cleaning import build_cleaning_recommendations
from app.datasets.evidence import (
    FACT_CATEGORY_DISTRIBUTION,
    FACT_CATEGORY_HEALTH,
    FACT_CATEGORY_QUALITY,
    FACT_CATEGORY_RELATIONSHIP,
    FACT_CATEGORY_SEGMENT,
    FACT_CATEGORY_STRUCTURE,
    FACT_CATEGORY_TEXT,
    FACT_CATEGORY_TREND,
    FACT_SCOPE_KEY_FINDING,
    FACT_SCOPE_QUALITY,
    FACT_SCOPE_TEXT,
    FACT_SCOPE_TREND,
    DatasetFact,
    build_facts,
)
from app.datasets.insights import (
    _contains_banned_interpretation,
    _deterministic_actions,
    build_fallback_summary,
    build_summary_highlights,
    evidence_vocabulary,
    scrub_unsupported_sentences,
    validate_dataset_output,
)
from app.datasets.loader import load_dataset
from app.datasets.profiling import profile_dataset
from app.datasets.quality import (
    HEALTH_BANDS,
    build_quality_report,
    canonicalize_health_band_text,
    health_band,
    health_band_label,
)
from app.datasets.relationships import build_relationship_report
from app.datasets.temporal import build_temporal_report
from app.datasets.text_columns import analyze_text_columns
from app.schemas.text_intelligence import TextIntelligenceResult

from .conftest import ListDatasetSource, keyword_analyzer


# ------------------------------------------------------------------ fixtures


def _report(config, columns, rows):
    dataset = load_dataset(ListDatasetSource(columns, rows), config.max_analysis_rows)
    profiles = profile_dataset(dataset, config)
    return build_quality_report(dataset, profiles, config)


@pytest.fixture
def quality_empty_column(config):
    return _report(config, ["label", "unused"], [[f"row {index}", None] for index in range(50)])


@pytest.fixture
def quality_clean(config):
    return _report(
        config,
        ["label", "amount"],
        [[f"row {index}", str(index * 3 + 1)] for index in range(50)],
    )


@pytest.fixture
def quality_76(quality_empty_column):
    return replace(quality_empty_column, health_score=76, health_band=health_band(76))


# ------------------------------------------------------- the band, in prose


def test_band_label_is_the_prose_form_of_the_band():
    for minimum, label in HEALTH_BANDS:
        assert health_band_label(minimum) == label.capitalize()


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (
            "The dataset has a health score of 76/100 (good), indicating it is usable.",
            "The dataset has a health score of 76/100 (fair), indicating it is usable.",
        ),
        ("Health: 76/100 (Good)", "Health: 76/100 (Fair)"),
        ("76/100 [good]", "76/100 [fair]"),
        ("76 / 100 ( good )", "76 / 100 ( fair )"),
    ],
)
def test_a_stale_band_word_is_rewritten_from_the_score(stored, expected):
    assert canonicalize_health_band_text(stored) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Health score 76/100 (fair) with 3 issues.",
        "Scored 95/100 (excellent).",
        "85/100 (median)",
        "12/100 (draft)",
        "Reviewed 76/100 pages",
        "",
    ],
)
def test_text_that_is_already_right_is_untouched(text):
    assert canonicalize_health_band_text(text) == text


def test_two_scores_in_one_sentence_each_get_their_own_band():
    corrected = canonicalize_health_band_text(
        "It moved from 76/100 (good) to 100/100 (fair) after the fix."
    )
    assert corrected == "It moved from 76/100 (fair) to 100/100 (excellent) after the fix."


def test_every_band_in_the_table_round_trips():
    for score in range(0, 101):
        rewritten = canonicalize_health_band_text(f"{score}/100 (excellent)")
        assert rewritten == f"{score}/100 ({health_band(score)})"


def test_the_fallback_summary_states_the_band_the_badge_shows(quality_76):
    summary = build_fallback_summary({"row_count": 10, "column_count": 2}, quality_76, [], None, [])
    assert "76/100 (Fair)" in summary.data_health
    assert "good" not in summary.data_health.lower()


# ------------------------------------ unsupported claims, by concept not phrase


@pytest.mark.parametrize(
    "claim",
    [
        "This finding may indicate a need to focus on other aspects of engagement.",
        "Readers appear engaged with the material.",
        "Suggests the audience is not interested in the topic.",
        "A sign of low motivation among respondents.",
        "Indicates a short attention span.",
        "Roughly a third of respondents have a diagnosis.",
        "The prevalence in this group is unusually high.",
    ],
)
def test_claims_the_engine_cannot_measure_are_caught(claim):
    assert _contains_banned_interpretation(claim) is not None


@pytest.mark.parametrize(
    "text",
    [
        "66.2% of the analyzed sample was classified as neutral.",
        "This is an interesting distribution to compare against the next export.",
        "Two columns are completely empty.",
        "The classifier detected no clear positive or negative sentiment.",
    ],
)
def test_measured_statements_are_not_caught(text):
    assert _contains_banned_interpretation(text) is None


def test_a_concept_the_dataset_actually_measures_is_allowed():
    measured = "the 'engagement_score' column ranges from 0 to 100"
    assert (
        _contains_banned_interpretation("Engagement is highest in June", measured=measured) is None
    )
    assert (
        _contains_banned_interpretation("This shows low motivation", measured=measured) is not None
    )


def test_evidence_vocabulary_covers_statements_and_column_names():
    fact = DatasetFact(
        fact_id="f1",
        scope=FACT_SCOPE_QUALITY,
        statement="'engagement_score' has 4 distinct values.",
        columns=["engagement_score"],
        measures={},
        weight=10.0,
    )
    vocabulary = evidence_vocabulary([fact], ["engagement_score", "signups"])
    assert "engagement_score" in vocabulary
    assert "signups" in vocabulary


def test_the_read_side_scrub_drops_only_the_offending_sentence():
    scrubbed = scrub_unsupported_sentences(
        "Most analyzed responses are neutral. This may indicate a lack of engagement. "
        "66.2% of the sample was classified as neutral."
    )
    assert scrubbed == (
        "Most analyzed responses are neutral. 66.2% of the sample was classified as neutral."
    )


def test_the_scrub_returns_empty_when_nothing_survives():
    assert scrub_unsupported_sentences("This proves the audience is disengaged.") == ""


def test_generated_output_carrying_an_unmeasured_claim_is_rejected():
    raw = {
        "insights": [
            {
                "type": "key_finding",
                "title": "Most responses are neutral",
                "explanation": "66.2% of the analyzed sample was neutral.",
                "evidence": "66.2% neutral.",
                "evidence_fact_ids": ["f1"],
                # The claim hides in `impact`, which the phrase list checked
                # but which no listed phrase matched.
                "impact": "Suggests a need to focus on other aspects of engagement.",
                "confidence": "high",
            }
        ]
    }
    with pytest.raises(Exception):
        validate_dataset_output(raw, {"f1"})


# ------------------------------------------------- the executive summary body


def _fact(category: str, statement: str, weight: float = 50.0) -> DatasetFact:
    return DatasetFact(
        fact_id=f"f{abs(hash(statement)) % 997}",
        scope=FACT_SCOPE_KEY_FINDING,
        statement=statement,
        columns=[],
        measures={},
        weight=weight,
        category=category,
    )


def test_summary_highlights_take_one_statement_per_category_in_a_fixed_order():
    facts = [
        _fact(FACT_CATEGORY_TREND, "Row volume declined 88.5%."),
        _fact(FACT_CATEGORY_TEXT, "66.2% of the analyzed sample was neutral."),
        _fact(FACT_CATEGORY_QUALITY, "All 15,628 missing cells come from 2 empty columns."),
        _fact(FACT_CATEGORY_STRUCTURE, "The dataset holds 7,814 rows across 9 columns."),
        _fact(FACT_CATEGORY_QUALITY, "A second quality statement about the same subject."),
        _fact(FACT_CATEGORY_HEALTH, "The dataset health score is 76/100 (fair)."),
    ]
    highlights = build_summary_highlights(facts)

    assert highlights == [
        "The dataset holds 7,814 rows across 9 columns.",
        "All 15,628 missing cells come from 2 empty columns.",
        "66.2% of the analyzed sample was neutral.",
        "Row volume declined 88.5%.",
    ]


def test_summary_highlights_are_verbatim_and_bounded():
    categories = (
        FACT_CATEGORY_STRUCTURE,
        FACT_CATEGORY_QUALITY,
        FACT_CATEGORY_TEXT,
        FACT_CATEGORY_TREND,
        FACT_CATEGORY_RELATIONSHIP,
        FACT_CATEGORY_SEGMENT,
        FACT_CATEGORY_DISTRIBUTION,
    )
    facts = [_fact(category, f"Statement {category}") for category in categories]
    highlights = build_summary_highlights(facts)
    assert len(highlights) <= 5
    for statement in highlights:
        assert statement in {fact.statement for fact in facts}


def test_an_uncategorised_fact_is_never_promoted_to_the_summary():
    assert build_summary_highlights([_fact("", "Something with no category.")]) == []


def test_summary_highlights_of_an_empty_analysis_are_empty():
    assert build_summary_highlights([]) == []


# --------------------------------------------------------- recommended actions


def test_the_empty_column_action_says_what_to_verify_and_what_it_decides(quality_empty_column):
    actions = _deterministic_actions(quality_empty_column, None, [])
    assert actions
    first = actions[0]
    assert "Verify whether" in first
    assert "source or export" in first
    assert "no values at all" in first
    assert "Investigate" not in first


def test_a_sharp_volume_change_produces_a_collection_process_action(quality_clean):
    trend = DatasetFact(
        fact_id="f9",
        scope=FACT_SCOPE_TREND,
        statement="Row volume is declining.",
        columns=["occurred_at"],
        measures={"period_over_period_percentage": -88.5},
        weight=70.0,
    )
    actions = _deterministic_actions(quality_clean, None, [trend])
    assert any("collection or export process" in action for action in actions)
    assert any("-88.5%" in action for action in actions)
    assert any("occurred_at" in action for action in actions)


def test_a_flat_series_produces_no_trend_action(quality_clean):
    trend = DatasetFact(
        fact_id="f9",
        scope=FACT_SCOPE_TREND,
        statement="Row volume is stable.",
        columns=["occurred_at"],
        measures={"period_over_period_percentage": 1.2},
        weight=70.0,
    )
    actions = _deterministic_actions(quality_clean, None, [trend])
    assert not any("collection or export process" in action for action in actions)


def test_no_action_is_a_bare_instruction_to_investigate(quality_empty_column):
    for action in _deterministic_actions(quality_empty_column, None, []):
        assert action.strip().lower() not in {"investigate this.", "investigate this"}
        assert len(action.split()) > 6


# ------------------------------------------------------ measured denominators


def test_each_affected_column_carries_its_own_row_denominator(config):
    rows = [[f"row {index}", None] for index in range(40)]
    dataset = load_dataset(ListDatasetSource(["label", "unused"], rows), config.max_analysis_rows)
    profiles = profile_dataset(dataset, config)
    report = build_quality_report(dataset, profiles, config)

    concentration = report.missing_concentration
    assert concentration is not None
    entry = next(item for item in concentration.top_columns if item["column"] == "unused")
    # "40 missing" alone is not a fact; "40 / 40" is.
    assert entry["analyzed_rows"] == 40
    assert entry["missing_count"] == 40


# ---------------------------------------------- cleaning says what to do, once


def test_a_recommendation_explains_the_action_not_the_diagnosis(config):
    rows = [[f"row {index}", None] for index in range(30)]
    dataset = load_dataset(ListDatasetSource(["label", "unused"], rows), config.max_analysis_rows)
    profiles = profile_dataset(dataset, config)
    report = build_quality_report(dataset, profiles, config)

    recommendations = build_cleaning_recommendations(report)
    assert recommendations
    for recommendation in recommendations:
        assert recommendation.why
        assert recommendation.why != recommendation.reason
        assert recommendation.why != recommendation.expected_impact


# ----------------------------------------- the sentiment statement, end to end


@pytest.fixture
def sampled_text_analysis(config):
    bounded = replace(config, text_rows_per_column=25)
    rows = [
        [f"A written response about topic number {index} and what happened next"]
        for index in range(100)
    ]
    dataset = load_dataset(ListDatasetSource(["comment"], rows), bounded.max_analysis_rows)
    profiles = profile_dataset(dataset, bounded)
    quality = build_quality_report(dataset, profiles, bounded)
    text = analyze_text_columns(dataset, profiles, bounded, keyword_analyzer)
    relationships = build_relationship_report(dataset, profiles, bounded)
    temporal = build_temporal_report(dataset, profiles, bounded)
    return build_facts(dataset, profiles, quality, relationships, temporal, text)


def test_the_sentiment_fact_leads_with_the_finding_then_the_evidence_then_the_scope(
    sampled_text_analysis,
):
    sentiment = next(
        fact
        for fact in sampled_text_analysis
        if fact.scope == FACT_SCOPE_TEXT and "classified as" in fact.statement
    )
    statement = sentiment.statement

    assert statement.startswith("Most analyzed responses in 'comment'") or statement.startswith(
        "The most common classification in 'comment'"
    )
    assert "of the analyzed sample was classified as" in statement
    assert "Based on 25 of 100 text rows (25% coverage, systematic sample)." in statement
    assert _contains_banned_interpretation(statement) is None


def test_a_neutral_result_says_what_neutral_does_not_mean(config):
    def neutral_analyzer(texts):
        return [
            TextIntelligenceResult(
                original_text=text,
                processed_text=text.lower(),
                detected_language="en",
                routing_category="english",
                processable=True,
                analyzed=True,
                sentiment="neutral",
                confidence=0.8,
                intent={"primary_intent": "opinion", "intents": []},
            )
            for text in texts
        ]

    bounded = replace(config, text_rows_per_column=25)
    rows = [[f"Record {index} was filed on the following working day"] for index in range(100)]
    dataset = load_dataset(ListDatasetSource(["note"], rows), bounded.max_analysis_rows)
    profiles = profile_dataset(dataset, bounded)
    text = analyze_text_columns(dataset, profiles, bounded, neutral_analyzer)

    facts = build_facts(
        dataset,
        profiles,
        build_quality_report(dataset, profiles, bounded),
        build_relationship_report(dataset, profiles, bounded),
        build_temporal_report(dataset, profiles, bounded),
        text,
    )
    sentiment = next(fact for fact in facts if "classified as neutral" in fact.statement)
    assert "not a measure of how engaged or interested" in sentiment.statement
    assert "Based on 25 of 100 text rows" in sentiment.statement


def test_the_summary_action_list_is_computed_even_on_the_ai_path(quality_empty_column, monkeypatch):
    from app.datasets import insights as module

    selection = module.DatasetInsightSelection(
        dataset_summary={"row_count": 50, "column_count": 2, "file_name": "seed.csv"},
        coverage={"total_rows": 50, "analyzed_rows": 50},
        columns=[],
        facts=[
            DatasetFact(
                fact_id="f1",
                scope=FACT_SCOPE_QUALITY,
                statement="'unused' is completely empty.",
                columns=["unused"],
                measures={},
                weight=80.0,
                category=FACT_CATEGORY_QUALITY,
            )
        ],
    )

    class _Outcome:
        status = "success"
        provider_used = "stub"
        model_used = "stub"
        result_json = {
            "insights": [
                {
                    "type": "data_quality_risk",
                    "title": "A column is empty",
                    "explanation": "'unused' has no values.",
                    "evidence": "'unused' is completely empty.",
                    "evidence_fact_ids": ["f1"],
                    "impact": "Nothing can be read from it.",
                    "confidence": "high",
                }
            ],
            "executive_summary": {
                "scope": "50 rows.",
                "data_health": "The health score is 76/100 (good).",
                "strongest_findings": ["Something the model wrote."],
                "key_risks": [],
                "recommended_actions": ["Investigate this."],
            },
        }

    class _Service:
        def generate(self, package):
            return _Outcome()

    result = module.generate_dataset_insights(selection, quality_empty_column, _Service())

    assert result.generated_by == "ai"
    assert "76/100 (fair)" in result.executive_summary.data_health
    assert result.executive_summary.strongest_findings == ["'unused' is completely empty."]
    assert "Investigate this." not in result.executive_summary.recommended_actions
    assert any(
        "Verify whether" in action for action in result.executive_summary.recommended_actions
    )


def test_representative_examples_carry_no_markup_from_the_export(config):
    from app.datasets.text_columns import _display_excerpt

    rows = [
        [
            f"Thank you for episode {index}.<br>It explained something "
            f"I had never seen put into words.<br><br>Please make more."
        ]
        for index in range(60)
    ]
    dataset = load_dataset(ListDatasetSource(["comment"], rows), config.max_analysis_rows)
    profiles = profile_dataset(dataset, config)
    report = analyze_text_columns(dataset, profiles, config, keyword_analyzer)

    column = report.columns[0]
    quoted = [
        example.excerpt
        for group in (
            column.positive_examples,
            column.negative_examples,
            column.complaints,
            column.requests,
        )
        for example in group
    ]
    assert quoted, "the fixture should produce representative examples"
    for excerpt in quoted:
        assert "<br>" not in excerpt
        assert "&nbsp;" not in excerpt
        assert "Please make more." in excerpt or "Thank you for episode" in excerpt

    assert _display_excerpt("one<br><br>two") == "one two"
    assert _display_excerpt("plain text") == "plain text"
