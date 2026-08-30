"""The Overview / Data Quality refinement pass.

Everything here is checked against values counted from the fixture rather
than against the engine's own output, so a change that makes the numbers
agree with themselves but disagree with the file still fails.
"""

import pytest

from app.datasets.evidence import build_facts
from app.datasets.insights import (
    _contains_banned_interpretation,
    build_fallback_insights,
    build_fallback_summary,
    validate_dataset_output,
)
from app.datasets.loader import load_dataset
from app.datasets.profiling import profile_dataset
from app.datasets.quality import (
    HEALTH_BANDS,
    QualityIssueType,
    build_quality_report,
    health_band,
)
from app.datasets.relationships import build_relationship_report
from app.datasets.temporal import build_temporal_report
from app.datasets.text_columns import (
    _clean_text_for_terms,
    _example_score,
    _is_quotable,
    _is_useful_term,
    _normalize_arabic,
    _themes,
    analyze_text_columns,
)

from .conftest import ListDatasetSource, keyword_analyzer


def _pipeline(columns, rows, config, analyzer=None):
    dataset = load_dataset(ListDatasetSource(columns, rows), config.max_analysis_rows)
    profiles = profile_dataset(dataset, config)
    quality = build_quality_report(dataset, profiles, config)
    return dataset, profiles, quality


# ------------------------------------------------------- health bands


@pytest.mark.parametrize(
    "score,expected",
    [
        (100, "excellent"),
        (90, "excellent"),
        (89, "good"),
        (80, "good"),
        (79, "fair"),
        # The case that motivated the change: 76 read as "good".
        (76, "fair"),
        (65, "fair"),
        (64, "poor"),
        (40, "poor"),
        (39, "critical"),
        (0, "critical"),
    ],
)
def test_health_band_thresholds(score, expected):
    assert health_band(score) == expected


def test_health_bands_are_contiguous_and_ordered():
    """A gap or an inversion in the table would make some score unlabelled
    or mislabelled, which is exactly the defect this replaced."""
    minimums = [minimum for minimum, _label in HEALTH_BANDS]
    assert minimums == sorted(minimums, reverse=True)
    assert minimums[-1] == 0
    for score in range(0, 101):
        assert health_band(score) in {label for _minimum, label in HEALTH_BANDS}


# --------------------------------------------------- missing concentration


def _adhd_shaped(config, rows=200):
    """Two entirely empty columns, every other column complete -- the shape
    that made "22% missing" read as a dataset riddled with gaps."""
    data = [[str(i), "some text value", None, None] for i in range(rows)]
    return _pipeline(["id", "body", "rating", "language"], data, config)


def test_missing_concentration_attributes_every_gap_to_the_empty_columns(config):
    _dataset, _profiles, quality = _adhd_shaped(config)
    concentration = quality.missing_concentration

    assert concentration is not None
    assert concentration.concentrated is True
    assert concentration.empty_columns == ["rating", "language"]
    assert concentration.empty_column_share_percentage == 100.0
    assert concentration.top_share_percentage == 100.0
    assert concentration.populated_columns_complete is True
    # Counted from the fixture: 200 rows x 2 empty columns.
    assert concentration.missing_cells == 400
    assert sum(entry["share_of_missing"] for entry in concentration.top_columns) == 100.0


def test_missing_concentration_is_reported_as_spread_when_it_is(config):
    rows = [
        [None if index % 5 == 0 else "a", None if index % 3 == 0 else "b"] for index in range(90)
    ]
    _dataset, _profiles, quality = _pipeline(["one", "two"], rows, config)
    concentration = quality.missing_concentration
    assert concentration is not None
    assert concentration.empty_columns == []
    assert concentration.populated_columns_complete is False


def test_no_concentration_for_a_complete_dataset(config):
    rows = [["a", "b"] for _ in range(30)]
    _dataset, _profiles, quality = _pipeline(["one", "two"], rows, config)
    assert quality.missing_concentration is None


# -------------------------------------------------------- projected health


def test_projection_is_exact_arithmetic_over_published_penalties(config):
    _dataset, _profiles, quality = _adhd_shaped(config)
    resolvable = sum(
        issue.score_penalty
        for issue in quality.issues
        if issue.issue_type in (QualityIssueType.empty_column, QualityIssueType.duplicate_rows)
    )
    assert quality.projected_health_score == round(quality.health_score + resolvable)
    assert quality.resolvable_penalty == pytest.approx(resolvable)
    assert "empty_column" in quality.resolvable_issue_types


def _missing_only(config):
    """One column with scattered gaps and NO duplicate rows -- a second
    column keeps every row distinct, so the only issue is the missing one."""
    rows = [[str(index), None if index % 4 == 0 else str(index * 3)] for index in range(80)]
    return _pipeline(["row_no", "metric"], rows, config)


def test_projection_excludes_issues_that_need_a_human_decision(config):
    """Missing values can be imputed or dropped, and the resulting score
    depends on which -- so it must never be projected."""
    _dataset, _profiles, quality = _missing_only(config)
    assert any(issue.issue_type == QualityIssueType.missing_values for issue in quality.issues)
    assert "missing_values" not in quality.resolvable_issue_types


def test_projection_is_omitted_when_nothing_is_resolvable(config):
    _dataset, _profiles, quality = _missing_only(config)
    assert {issue.issue_type for issue in quality.issues} == {QualityIssueType.missing_values}
    assert quality.projected_health_score is None
    assert quality.resolvable_issue_types == []


# ------------------------------------------------------------ checks


def test_checks_distinguish_passed_from_not_applicable(config):
    _dataset, _profiles, quality = _adhd_shaped(config)
    by_key = {check.check: check for check in quality.checks}

    assert by_key["duplicate_rows"].status == "passed"
    # No date column exists, so the date check did not run -- reporting that
    # as a pass would claim a check that never happened.
    assert by_key["date_validity"].status == "not_applicable"
    assert by_key["date_validity"].coverage == "none"
    assert by_key["empty_columns"].status == "issues_found"


def test_missing_values_check_wording_is_truthful_with_empty_columns(config):
    """400 cells ARE missing here; what passed is the scattered-gaps check."""
    _dataset, _profiles, quality = _adhd_shaped(config)
    check = next(item for item in quality.checks if item.check == "missing_values")
    assert check.status == "passed"
    assert check.detail == "No populated column has missing values"


# ------------------------------------------------------- keyword cleanup


def test_markup_never_becomes_a_theme():
    texts = ["a real sentence here<br>and another line", "more real words<br>plus this"] * 3
    terms = [entry["term"] for entry in _themes(texts)]
    assert "br" not in terms
    assert not _is_useful_term("br")
    assert "<br>" not in _clean_text_for_terms("x<br>y")


def test_shared_links_never_become_themes():
    """A pasted URL is not something the writer said; its host and path
    segments were ranking as themes."""
    texts = [
        "check https://www.example.com/watch?v=abc for a really useful explanation",
        "see www.example.com/watch for another really useful explanation here",
    ] * 3
    terms = [entry["term"] for entry in _themes(texts)]
    for fragment in ("example", "watch", "com", "https", "www"):
        assert fragment not in terms, fragment
    assert "explanation" in terms


def test_arabic_orthographic_variants_merge_into_one_theme():
    """The same word spelled two ways ranked twice, each with half its real
    support."""
    assert _normalize_arabic("حلقة") == _normalize_arabic("حلقه")
    texts = ["حلقة رائعة جدا", "حلقه رائعة جدا", "حلقة اخرى مفيدة", "حلقه اخرى مفيدة"]
    terms = [entry["term"] for entry in _themes(texts)]
    assert len(terms) == len(set(terms))
    episode = [
        entry
        for entry in _themes(texts)
        if _normalize_arabic(entry["term"]) == _normalize_arabic("حلقة")
    ]
    assert len(episode) == 1
    assert episode[0]["rows"] == 4


def test_domain_terms_are_kept_however_frequent():
    assert _is_useful_term("adhd")
    texts = ["ADHD is discussed here at length"] * 5
    assert "adhd" in [entry["term"] for entry in _themes(texts)]


def test_generic_filler_is_dropped():
    for filler in ("ده", "دي", "ناس", "just", "really"):
        assert not _is_useful_term(filler), filler


# ------------------------------------------------- representative examples


def test_a_single_generic_word_is_never_quoted_as_representative():
    assert _is_quotable("مشكلة") is False
    assert _is_quotable("problem") is False
    assert _is_quotable("This is a real sentence with substance to it") is True


def test_example_scoring_prefers_substance_over_position():
    substantial = _example_score("A clear, specific complaint about the export timing out", 0.8)
    thin = _example_score("bad thing here ok", 0.99)
    assert substantial > thin


def test_examples_are_ranked_and_de_duplicated(config):
    body = "This is a substantial piece of written feedback about the product"
    rows = [["short bad"], [body], [body], ["another substantial written response about pricing"]]
    rows += [[body] for _ in range(6)]
    dataset = load_dataset(ListDatasetSource(["feedback"], rows), config.max_analysis_rows)
    profiles = profile_dataset(dataset, config)
    report = analyze_text_columns(dataset, profiles, config, keyword_analyzer)

    if report.columns:
        column = report.columns[0]
        excerpts = [example.excerpt for example in column.positive_examples]
        assert len(excerpts) == len(set(excerpts))
        assert all(len(text.split()) >= 4 for text in excerpts)


# ------------------------------------------------ sentiment ratio + scope


def test_sentiment_ratio_only_when_both_sides_exist(config):
    rows = [["I really love this product and use it daily"] for _ in range(10)]
    rows += [["This is terrible and broken and I hate using it"] for _ in range(5)]
    dataset = load_dataset(ListDatasetSource(["feedback"], rows), config.max_analysis_rows)
    profiles = profile_dataset(dataset, config)
    column = analyze_text_columns(dataset, profiles, config, keyword_analyzer).columns[0]
    assert column.positive_to_negative_ratio == pytest.approx(2.0)

    positive_only = [["I really love this product and use it daily"] for _ in range(10)]
    dataset = load_dataset(ListDatasetSource(["feedback"], positive_only), config.max_analysis_rows)
    profiles = profile_dataset(dataset, config)
    column = analyze_text_columns(dataset, profiles, config, keyword_analyzer).columns[0]
    assert column.positive_to_negative_ratio is None


def test_sampled_text_facts_always_state_their_coverage(config):
    from dataclasses import replace

    bounded = replace(config, text_rows_per_column=20)
    # Varied text: 200 identical rows would be a CONSTANT column, not free
    # text, and would never reach the text stage at all.
    rows = [
        [f"This is a substantial written response about experience number {index}"]
        for index in range(200)
    ]
    dataset = load_dataset(ListDatasetSource(["feedback"], rows), bounded.max_analysis_rows)
    profiles = profile_dataset(dataset, bounded)
    quality = build_quality_report(dataset, profiles, bounded)
    text = analyze_text_columns(dataset, profiles, bounded, keyword_analyzer)
    relationships = build_relationship_report(dataset, profiles, bounded)
    temporal = build_temporal_report(dataset, profiles, bounded)

    facts = build_facts(dataset, profiles, quality, relationships, temporal, text)
    text_facts = [fact for fact in facts if "feedback" in fact.columns]
    assert text_facts
    for fact in text_facts:
        assert "analyzed sample" in fact.statement or "Based on" in fact.statement
        assert "20 of 200 text rows" in fact.statement
        assert "coverage" in fact.statement


# -------------------------------------------- unsupported interpretations


@pytest.mark.parametrize(
    "phrase",
    [
        "mostly neutral, suggesting limited engagement",
        "this indicates low engagement from the audience",
        "a lack of interest in the topic",
        "responses were largely apathetic",
    ],
)
def test_engagement_interpretations_are_detected(phrase):
    assert _contains_banned_interpretation(phrase) is not None


def test_neutral_sentiment_alone_is_not_flagged():
    assert (
        _contains_banned_interpretation(
            "66.2% of responses were classified as neutral within the analyzed sample."
        )
        is None
    )


def test_ai_insight_claiming_low_engagement_is_discarded():
    raw = {
        "insights": [
            {
                "type": "key_finding",
                "title": "Neutral responses dominate",
                "explanation": "66.2% were neutral, suggesting limited engagement from viewers.",
                "evidence": "66.2% neutral",
                "evidence_fact_ids": ["f1"],
                "impact": "Unclear",
                "confidence": "high",
            },
            {
                "type": "key_finding",
                "title": "Neutral responses dominate",
                "explanation": "Within the analyzed sample, 66.2% of responses were neutral.",
                "evidence": "66.2% neutral of 1,954 analyzed rows",
                "evidence_fact_ids": ["f1"],
                "impact": "Sentiment is not a strong signal in this column.",
                "confidence": "high",
            },
        ]
    }
    insights, _summary = validate_dataset_output(raw, {"f1"})
    assert len(insights) == 1
    assert "limited engagement" not in insights[0].explanation


def test_ai_executive_summary_claiming_low_engagement_is_discarded():
    raw = {
        "insights": [
            {
                "type": "key_finding",
                "title": "Fine",
                "explanation": "Within the analyzed sample, 50% were positive.",
                "evidence": "50%",
                "evidence_fact_ids": ["f1"],
                "impact": "Matters",
                "confidence": "high",
            }
        ],
        "executive_summary": {
            "scope": "A dataset of comments.",
            "data_health": "Health 76/100.",
            "strongest_findings": ["Mostly neutral, suggesting low engagement."],
            "key_risks": [],
            "recommended_actions": ["Look into it."],
        },
    }
    _insights, summary = validate_dataset_output(raw, {"f1"})
    assert summary is None


# ---------------------------------------------------- actionable actions


def test_deterministic_actions_name_what_to_act_on(config):
    _dataset, profiles, quality = _adhd_shaped(config)
    facts_insights = build_fallback_insights([], quality)
    coverage = {
        "areas": [
            {
                "area": "text",
                "status": "sampled",
                "coverage_percentage": 25.0,
            }
        ]
    }
    summary = build_fallback_summary(
        {"row_count": 200, "column_count": 4, "file_name": "x.xlsx"},
        quality,
        facts_insights,
        coverage,
    )
    actions = " ".join(summary.recommended_actions)
    assert "rating" in actions and "language" in actions
    assert "health score to" in actions
    assert "coverage" in actions
    assert "Investigate this" not in actions


# ------------------------------------------------------- no repetition


def test_one_concentration_insight_replaces_the_per_column_ones(config):
    dataset, profiles, quality = _adhd_shaped(config)
    relationships = build_relationship_report(dataset, profiles, config)
    temporal = build_temporal_report(dataset, profiles, config)
    text = analyze_text_columns(dataset, profiles, config, keyword_analyzer)
    facts = build_facts(dataset, profiles, quality, relationships, temporal, text)

    empty_facts = [fact for fact in facts if "is empty in" in fact.statement]
    assert empty_facts == []
    concentration_facts = [fact for fact in facts if "completely empty column" in fact.statement]
    assert len(concentration_facts) == 1


def test_context_facts_never_become_insights(config):
    dataset, profiles, quality = _adhd_shaped(config)
    relationships = build_relationship_report(dataset, profiles, config)
    temporal = build_temporal_report(dataset, profiles, config)
    text = analyze_text_columns(dataset, profiles, config, keyword_analyzer)
    facts = build_facts(dataset, profiles, quality, relationships, temporal, text)

    assert any(fact.context_only for fact in facts)
    insights = build_fallback_insights(facts, quality)
    for insight in insights:
        assert "The dataset holds" not in insight.explanation
        assert "The dataset health score is" not in insight.explanation
