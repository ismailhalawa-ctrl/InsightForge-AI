"""Text Intelligence for the free-text columns of a dataset.

Two rules govern this stage, and both are about NOT running:

  1. Only columns whose detected semantic role is `free_text` are analyzed.
     Identifiers, emails, URLs, category labels, booleans and dates are
     excluded by role (see NON_TEXT_ROLES), not by a length heuristic that a
     long product code would defeat. Running sentiment over a column of SKUs
     produces confident percentages about nothing.

  2. Work is bounded per column (DATASET_TEXT_ROWS_PER_COLUMN) and across
     columns (DATASET_MAX_TEXT_COLUMNS), with the sampled share reported.
     A 200,000-row feedback column costs the same as a 2,000-row one, and
     the result says which it was.

The analysis itself is not reimplemented here. The existing
TextIntelligenceService -- the same pipeline every YouTube, Reddit and GitHub
analysis runs -- is injected as a callable, so language detection, sentiment
fusion, spam filtering and intent classification are the product's own, not
a second implementation that could disagree with them.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from app.datasets.column_types import SemanticRole
from app.datasets.config import DatasetAnalysisConfig
from app.datasets.contracts import NormalizedDataset
from app.datasets.profiling import ColumnProfile
from app.schemas.text_intelligence import TextIntelligenceResult
from app.services.insights.local.keywords import tokenize

TextAnalyzer = Callable[[list[str]], list[TextIntelligenceResult]]

# Excerpt length for a quoted example. Long enough to be recognisable, short
# enough that the API response is not a re-export of the user's data.
EXAMPLE_MAX_CHARS = 240

# Intents that answer "what do people want / what is wrong", mapped to the
# product's existing vocabulary so a dataset's complaints mean the same thing
# a YouTube analysis's complaints mean.
_COMPLAINT_INTENTS = frozenset({"complaint", "criticism"})
_REQUEST_INTENTS = frozenset({"request", "suggestion"})

_MIN_THEME_SUPPORT = 2
_MAX_THEMES = 8

# Markup that survives into a text column when the source exported HTML.
# Observed on a real upload: `br` was the single most frequent "theme" in a
# column of YouTube comments, purely because <br> is how line breaks were
# stored. These are artefacts of transport, never things people wrote about.
_MARKUP_TOKENS = frozenset(
    {
        "br",
        "nbsp",
        "amp",
        "quot",
        "apos",
        "lt",
        "gt",
        "div",
        "span",
        "href",
        "http",
        "https",
        "www",
        "com",
    }
)

_MARKUP_PATTERN = re.compile(r"<[^>]{1,20}>|&[a-z]{2,6};", re.IGNORECASE)

# A pasted link is not something the writer said. Left in, its host and path
# segments tokenize into words and rank as themes -- observed on a real
# upload, where the domain and a path segment both placed in the top eight
# purely because people shared links. Removed generically: no host or
# product name is named here.
_URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)

# Very common words that survive the shared tokenizer but carry no analytical
# value on their own. Kept deliberately short and generic -- this is not a
# domain vocabulary, and a term is only excluded when it says nothing about
# ANY dataset. Domain terms (ADHD, a product name, a feature) are never here,
# however frequent they are.
_LOW_VALUE_TERMS = frozenset(
    {
        # English fillers the keyword tokenizer keeps
        "just",
        "really",
        "very",
        "thing",
        "things",
        "like",
        "want",
        "know",
        "make",
        "made",
        "get",
        "got",
        "one",
        "also",
        "even",
        "much",
        "many",
        "good",
        "great",
        "video",
        # Arabic demonstratives, fillers and generic quantifiers. These are
        # the direct equivalent of "this/that/some/people" and appear at the
        # top of every Arabic corpus regardless of subject.
        "ده",  # dah  (this)
        "دي",  # di   (this, fem.)
        "دة",  # da
        "دا",  # da
        "حد",  # hadd (someone)
        "ناس",  # nas  (people)
        "اللي",  # elli (which)
        "يعني",  # yaani (i.e.)
        "كده",  # kida (like that)
        "عشان",  # ashan (because)
        "فيه",  # feeh (there is)
        "اوي",  # awi (very)
        "جدا",  # giddan (very)
        "شي",  # shay (thing)
        "شيء",  # shay' (thing)
    }
)

# Minimum characters for a term to be reported as a theme at all. A one- or
# two-letter token is noise in every script.
_MIN_THEME_TERM_LENGTH = 3


def _normalize_arabic(term: str) -> str:
    """Folds the orthographic variants that make one word look like two.

    Arabic is routinely written with interchangeable forms -- alef with and
    without hamza, final ta-marbuta versus ha, final alef-maqsura versus ya.
    Without folding, the SAME word appears twice in a theme list (observed:
    the word for "episode" ranked separately in two spellings, each with half
    its real support). Only these safe, purely orthographic substitutions are
    applied; nothing is stemmed, so distinct words stay distinct.
    """
    folded = (
        term.replace("أ", "ا")  # alef hamza above -> alef
        .replace("إ", "ا")  # alef hamza below -> alef
        .replace("آ", "ا")  # alef madda -> alef
        .replace("ى", "ي")  # alef maqsura -> ya
        .replace("ة", "ه")  # ta marbuta -> ha
    )
    # Tashkeel (diacritics) and tatweel carry no lexical difference here.
    return re.sub("[ً-ْـ]", "", folded)


def _clean_text_for_terms(text: str) -> str:
    """Strips markup and links before tokenizing, so neither `<br>` nor a
    shared URL's host can become a theme."""
    return _MARKUP_PATTERN.sub(" ", _URL_PATTERN.sub(" ", text))


def _is_useful_term(term: str) -> bool:
    if len(term) < _MIN_THEME_TERM_LENGTH:
        return False
    if term in _MARKUP_TOKENS or term in _LOW_VALUE_TERMS:
        return False
    # A bare number is not a theme.
    return not term.isdigit()


# ---- representative-example selection ------------------------------------
#
# Examples used to be "the first five that matched", then sorted. Position in
# the file is not a measure of anything, and the result was that a one-word
# row like "problem" could represent every complaint in the column.

# An example must carry at least this many words to be quotable. One word is
# never evidence of anything, however confidently it was classified.
_MIN_EXAMPLE_WORDS = 4
_MIN_EXAMPLE_CHARS = 24
# Beyond this an excerpt stops being an example and becomes an essay.
_IDEAL_EXAMPLE_CHARS = 400


def _example_score(text: str, confidence: float | None) -> float:
    """How representative one row is, as a number.

    Substance first (a quotable example has to actually say something), then
    the classifier's own confidence. Length helps only up to a point: past
    the ideal it is penalised, because a 2,000-character comment is not a
    better illustration than a clear two-sentence one.
    """
    words = len(text.split())
    length = len(text)
    substance = min(words / 25.0, 1.0)
    if length > _IDEAL_EXAMPLE_CHARS:
        substance *= _IDEAL_EXAMPLE_CHARS / length
    return substance * 2.0 + (confidence or 0.0)


def _is_quotable(text: str) -> bool:
    stripped = _MARKUP_PATTERN.sub(" ", text).strip()
    return len(stripped) >= _MIN_EXAMPLE_CHARS and len(stripped.split()) >= _MIN_EXAMPLE_WORDS


def _select_examples(candidates: list[tuple[float, str, "TextExample"]], limit: int = 5):
    """Best-scoring, de-duplicated examples.

    De-duplication is on the normalised text, so the same comment posted
    twice cannot fill two of the five slots.
    """
    chosen: list[TextExample] = []
    seen: set[str] = set()
    for _score, key, example in sorted(candidates, key=lambda item: item[0], reverse=True):
        if key in seen:
            continue
        seen.add(key)
        chosen.append(example)
        if len(chosen) >= limit:
            break
    return chosen


@dataclass(frozen=True)
class TextExample:
    row_number: int
    excerpt: str
    sentiment: str
    confidence: float | None
    language: str


@dataclass(frozen=True)
class TextColumnAnalysis:
    column: str
    analyzed_count: int
    total_non_empty: int
    sampled: bool
    coverage_percentage: float
    average_length: float
    language_distribution: list[dict]
    sentiment_distribution: list[dict]
    dominant_sentiment: str | None
    # positive/negative, when BOTH are present. A ratio against zero is not
    # a ratio, and a ratio where one side is absent invites the reader to
    # infer a comparison the data cannot support.
    positive_to_negative_ratio: float | None
    positive_examples: list[TextExample]
    negative_examples: list[TextExample]
    complaints: list[TextExample]
    requests: list[TextExample]
    themes: list[dict]
    unanalyzable_count: int
    spam_count: int


@dataclass(frozen=True)
class TextIntelligenceReport:
    analyzable: bool
    unavailable_reason: str | None
    columns: list[TextColumnAnalysis] = field(default_factory=list)
    skipped_columns: list[dict] = field(default_factory=list)


def select_text_columns(
    profiles: list[ColumnProfile], config: DatasetAnalysisConfig
) -> tuple[list[ColumnProfile], list[dict]]:
    """The columns worth analyzing as prose, and why the rest were not.

    Ordered by average length descending: when the cap forces a choice, the
    column with the most written content in it is the one people actually
    wrote something in.
    """
    candidates = [
        profile
        for profile in profiles
        if profile.semantic_role == SemanticRole.free_text and profile.non_empty_count > 0
    ]
    skipped: list[dict] = []

    long_enough = []
    for profile in candidates:
        average = profile.text.average_length if profile.text else 0.0
        if average < config.text_min_average_length:
            skipped.append(
                {
                    "column": profile.name,
                    "reason": (
                        f"Values average {average:.0f} characters, below the "
                        f"{config.text_min_average_length}-character minimum for text analysis"
                    ),
                }
            )
            continue
        long_enough.append(profile)

    long_enough.sort(
        key=lambda profile: (profile.text.average_length if profile.text else 0.0), reverse=True
    )
    selected = long_enough[: config.max_text_columns]
    for profile in long_enough[config.max_text_columns :]:
        skipped.append(
            {
                "column": profile.name,
                "reason": f"Beyond the {config.max_text_columns}-text-column analysis cap",
            }
        )
    return selected, skipped


def _display_excerpt(text: str) -> str:
    """The row's own words, with export markup removed."""
    stripped = _MARKUP_PATTERN.sub(" ", text)
    return " ".join(stripped.split())


def _example(row_number: int, text: str, result: TextIntelligenceResult) -> TextExample:
    return TextExample(
        row_number=row_number,
        excerpt=_display_excerpt(text)[:EXAMPLE_MAX_CHARS],
        sentiment=result.sentiment or "uncertain",
        confidence=result.confidence,
        language=result.detected_language,
    )


def _themes(texts: list[str]) -> list[dict]:
    """Recurring terms across this column, using the product's existing
    keyword tokenizer (stopwords, Arabic prefixes and noise tokens already
    handled there).

    Deliberately a frequency count, not a topic model: this is the honest
    claim the data supports without embeddings, and a term appearing once is
    not a theme -- hence _MIN_THEME_SUPPORT.
    """
    counter: Counter[str] = Counter()
    document_frequency: Counter[str] = Counter()
    # Which surface spelling to show for a folded term -- the most frequent
    # one, so the label is a form the reader will recognise from the data.
    surface: dict[str, Counter[str]] = {}

    for text in texts:
        tokens = tokenize(_clean_text_for_terms(text).lower())
        folded = []
        for token in tokens:
            key = _normalize_arabic(token)
            if not _is_useful_term(key):
                continue
            folded.append(key)
            surface.setdefault(key, Counter())[token] += 1
        counter.update(folded)
        document_frequency.update(set(folded))

    return [
        {
            "term": surface[term].most_common(1)[0][0] if term in surface else term,
            "occurrences": counter[term],
            "rows": document_frequency[term],
            "share_of_rows": (
                round(100 * document_frequency[term] / len(texts), 2) if texts else 0.0
            ),
        }
        for term, _count in counter.most_common(_MAX_THEMES * 4)
        if document_frequency[term] >= _MIN_THEME_SUPPORT
    ][:_MAX_THEMES]


def analyze_text_columns(
    dataset: NormalizedDataset,
    profiles: list[ColumnProfile],
    config: DatasetAnalysisConfig,
    analyzer: TextAnalyzer,
) -> TextIntelligenceReport:
    selected, skipped = select_text_columns(profiles, config)
    if not selected:
        return TextIntelligenceReport(
            analyzable=False,
            unavailable_reason=(
                "No free-text column was detected in this dataset. Identifiers, category labels, "
                "emails, URLs and dates are deliberately excluded from text analysis -- running "
                "sentiment over them would produce confident results about nothing."
            ),
            skipped_columns=skipped,
        )

    analyses: list[TextColumnAnalysis] = []
    for profile in selected:
        raw = dataset.column_values(profile.index)
        rows = [
            (index + 1, value.strip())
            for index, value in enumerate(raw)
            if value is not None and value.strip()
        ]
        total_non_empty = len(rows)
        sampled = total_non_empty > config.text_rows_per_column
        if sampled:
            # Systematic, matching the loader: reproducible without a seed,
            # and spread across the column rather than its first rows.
            step = (
                total_non_empty + config.text_rows_per_column - 1
            ) // config.text_rows_per_column
            rows = rows[::step][: config.text_rows_per_column]

        texts = [text for _row, text in rows]
        results = analyzer(texts)

        languages = Counter(result.detected_language for result in results)
        sentiments = Counter(
            (result.sentiment or "uncertain")
            for result in results
            if result.analyzed and not result.spam.is_spam
        )
        analyzed_clean = sum(sentiments.values())

        # Every candidate is scored and ranked, rather than the first five
        # that matched being kept. See _example_score.
        positive_candidates: list[tuple[float, str, TextExample]] = []
        negative_candidates: list[tuple[float, str, TextExample]] = []
        complaint_candidates: list[tuple[float, str, TextExample]] = []
        request_candidates: list[tuple[float, str, TextExample]] = []

        for (row_number, text), result in zip(rows, results, strict=True):
            if result.spam.is_spam or not result.analyzed:
                continue
            if not _is_quotable(text):
                # A one-word row is not evidence, however confidently the
                # classifier labelled it. It still counts in every
                # distribution above -- it is only barred from being QUOTED
                # as representative.
                continue
            example = _example(row_number, text, result)
            entry = (
                _example_score(text, result.confidence),
                " ".join(text.split()).lower(),
                example,
            )
            if result.sentiment == "positive":
                positive_candidates.append(entry)
            elif result.sentiment == "negative":
                negative_candidates.append(entry)

            intents = set(result.intent.intents)
            primary = result.intent.primary_intent
            if intents & _COMPLAINT_INTENTS:
                complaint_candidates.append(entry)
            # A request is only listed when asking is what the row is mainly
            # DOING. Multi-label intent means a criticism that happens to
            # mention a suggestion carries both labels, and listing it as a
            # request put "your facts are wrong, see this source" under
            # Requests. The primary intent is what decides.
            if intents & _REQUEST_INTENTS and primary not in _COMPLAINT_INTENTS:
                request_candidates.append(entry)

        positives = _select_examples(positive_candidates)
        negatives = _select_examples(negative_candidates)
        complaints = _select_examples(complaint_candidates)
        requests = _select_examples(request_candidates)

        analyses.append(
            TextColumnAnalysis(
                column=profile.name,
                analyzed_count=len(results),
                total_non_empty=total_non_empty,
                sampled=sampled,
                coverage_percentage=(
                    round(100 * len(results) / total_non_empty, 2) if total_non_empty else 0.0
                ),
                average_length=profile.text.average_length if profile.text else 0.0,
                language_distribution=[
                    {
                        "language": language,
                        "count": count,
                        "percentage": round(100 * count / len(results), 2) if results else 0.0,
                    }
                    for language, count in languages.most_common()
                ],
                sentiment_distribution=[
                    {
                        "sentiment": sentiment,
                        "count": count,
                        "percentage": (
                            round(100 * count / analyzed_clean, 2) if analyzed_clean else 0.0
                        ),
                    }
                    for sentiment, count in sentiments.most_common()
                ],
                dominant_sentiment=(sentiments.most_common(1)[0][0] if sentiments else None),
                positive_to_negative_ratio=(
                    round(sentiments["positive"] / sentiments["negative"], 2)
                    if sentiments.get("positive") and sentiments.get("negative")
                    else None
                ),
                positive_examples=positives,
                negative_examples=negatives,
                complaints=complaints,
                requests=requests,
                themes=_themes(texts),
                unanalyzable_count=sum(1 for result in results if not result.analyzed),
                spam_count=sum(1 for result in results if result.spam.is_spam),
            )
        )

    return TextIntelligenceReport(
        analyzable=True, unavailable_reason=None, columns=analyses, skipped_columns=skipped
    )
