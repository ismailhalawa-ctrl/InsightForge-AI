"""Page-specific PROJECTIONS of one persisted Repository Intelligence result.

Four GitHub pages, four jobs:

    Overview    executive snapshot -- "tell me the truth in 60 seconds"
    Repository  technical deep dive -- "explain this codebase to a reviewer"
    Problems    diagnostic -- "what is weak, and what can go wrong"
    Requests    demand intelligence -- "what are people asking for"

Every model here is DERIVED, deterministically, from the SAME persisted
`RepositoryIntelligenceResult` the analysis job produced once, plus the
deterministic documentation/activity facts already in the analytics payload.
There is no second synthesis, no per-page generation, and no provider call
on any read path: navigating between the four pages costs zero AI calls, and
History renders all four with the provider offline.

Why projections rather than four lists of the same finding
----------------------------------------------------------
The failure this module exists to remove: one gap ("no security policy in
the analysed documentation") rendered as the SAME full card on Overview, on
Repository, on Problems and on Requests. Logically consistent, and a bad
product -- the reader learns the finding once and then scrolls past it three
more times.

So a finding appears at most once per page, in the SHAPE that page needs:

    Overview   severity + a one-sentence impact. No explanation body.
    Problems   the full diagnostic: explanation, impact, affected area,
               provenance, and one short next action.
    Requests   only as a decision: action, priority, effort, benefit --
               and only when no real community demand outranks it.
    Repository documentation gaps under documentation coverage; engineering
               risks in the technical improvement inventory. Never both.

The shapes are different TYPES, not different renderings of one type, so
"the same card on all four pages" is not something a caller can accidentally
reintroduce.

Provenance is a field, never an inference
-----------------------------------------
`provenance` on every item says where the claim came from -- community
evidence, the repository's own documentation, both, or InsightForge's
reading of the repository. A recommendation InsightForge derived must never
be presentable as demand a user expressed, and a missing file must never be
presentable as a defect: `finding_type` carries that second distinction on
every problem-shaped item.

Backward compatibility
----------------------
Everything here is computed at READ time from whatever the persisted result
contains. A result written under repo-v2 or repo-v3 has none of the repo-v4
metadata; the builder derives each missing field deterministically, so a
year-old analysis projects into all four pages without being regenerated and
without a migration.
"""

from pydantic import BaseModel, Field

# Page caps. These are CEILINGS, never quotas -- a repository with two
# honest risks shows two. Nothing is padded to reach a number.
MAX_OVERVIEW_STRENGTHS = 3
MAX_OVERVIEW_RISKS = 3
MAX_OVERVIEW_RECOMMENDATIONS = 3
MAX_OVERVIEW_GAPS = 5
MAX_PROBLEM_ITEMS = 8
MAX_DEMAND_ITEMS = 8
# The fallback opportunity list on Requests. Small on purpose: when there is
# no community demand, repeating every risk with the word "Add" in front of
# it is not demand intelligence, it is Problems again.
MAX_OPPORTUNITIES = 5
# The shortlist actually rendered when there is NO community demand.
#
# Lower than MAX_OPPORTUNITIES on purpose: "do not fill the page merely
# because recommendations exist". Four is the ceiling, three is the usual
# result once near-duplicates have collapsed, and the cap that matters more
# is the one applied when real demand IS present -- our advice drops to a
# short tail so the page stays a demand page.
MAX_FALLBACK_OPPORTUNITIES = 4


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


class GithubPageEvidenceRef(BaseModel):
    """One supporting record. `url` is resolved server-side from persisted
    records -- the model is never shown a URL and never asked for one, so a
    link here cannot be hallucinated. The excerpt is deliberately absent: a
    repository document can come from a private repository, and these
    projections are rendered into pages and PDFs."""

    evidence_id: str
    title: str | None = None
    url: str | None = None
    kind: str = "repository_document"


#: Where a claim came from. Rendered as a visible label, never inferred by
#: the frontend.
#:
#: "community_reported"    people wrote it in issues/PRs/comments/reviews
#: "repository_derived"    InsightForge's reading of the repository
#: "documentation_derived" a deterministic fact about which docs exist
#: "cross_source"          corroborated by community AND documentation
PROVENANCE_COMMUNITY = "community_reported"
PROVENANCE_REPOSITORY = "repository_derived"
PROVENANCE_DOCUMENTATION = "documentation_derived"
PROVENANCE_CROSS_SOURCE = "cross_source"

#: What KIND of thing a problem-shaped item is. The distinction that keeps a
#: missing file from being drawn like a runtime defect.
TYPE_DOCUMENTATION_GAP = "documentation_gap"
TYPE_ENGINEERING_RISK = "engineering_risk"
TYPE_OBSERVATION = "observation"


class GithubDocumentationGapItem(BaseModel):
    """A documentation area the analysis did not find.

    Modelled as an ABSENCE with a stated consequence, never as a defect.
    `impact` says what is unclear or unsupported as a result -- it never
    says the software is broken, because a missing file is not evidence that
    anything is.

    `category` is the deterministic classifier slug when this came from
    document classification, and None when it came from the synthesis (e.g.
    "the testing strategy is not documented", which no category covers).
    """

    gap_id: str
    category: str | None = None
    title: str
    importance: str = "medium"
    impact: str
    provenance: str = PROVENANCE_DOCUMENTATION
    evidence: list[GithubPageEvidenceRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Overview -- executive
# ---------------------------------------------------------------------------


class GithubAnalysisCoverage(BaseModel):
    """What evidence this analysis actually had. Replaces the three separate
    "no activity was collected" notices the Overview used to print, each in
    its own section, each saying the same thing."""

    documents_analyzed: int = 0
    issues_collected: int = 0
    pull_requests_collected: int = 0
    releases_collected: int = 0
    community_records_collected: int = 0
    community_evidence_available: bool = False
    #: "documentation" | "community" | "documentation_and_community" | "insufficient"
    analysis_basis: str = "insufficient"


class GithubOverviewStrength(BaseModel):
    """Compact. `why_it_matters` is one sentence -- the full inventory lives
    on Repository, and printing the whole explanation here is what made the
    Overview a second copy of that page."""

    strength_id: str
    title: str
    why_it_matters: str
    affected_area: str | None = None
    evidence: list[GithubPageEvidenceRef] = Field(default_factory=list)


class GithubOverviewRisk(BaseModel):
    """Deliberately has NO explanation field.

    That is the cross-page rule made structural: the Overview states what
    the risk is, how severe, and what it costs in one sentence. The
    diagnostic body belongs to Problems, and a type that cannot carry it
    cannot leak it here."""

    risk_id: str
    title: str
    #: "high" | "medium" | "low" | "unranked" -- the synthesis's own grade,
    #: never upgraded. "unranked" means it declined to grade, not "medium".
    severity: str = "unranked"
    impact: str
    finding_type: str = TYPE_ENGINEERING_RISK
    provenance: str = PROVENANCE_REPOSITORY
    evidence: list[GithubPageEvidenceRef] = Field(default_factory=list)


class GithubOverviewRecommendation(BaseModel):
    action: str
    priority: str = "unranked"
    expected_benefit: str | None = None
    #: Title of the risk this addresses, when one was paired. Lets the
    #: Overview link cause to cure without printing the risk card twice.
    related_risk: str | None = None
    evidence: list[GithubPageEvidenceRef] = Field(default_factory=list)


class GithubOverviewView(BaseModel):
    """The 60-second read.

    `snapshot` is None when the synthesis's summary merely restates the
    repository's own GitHub description -- the header already shows that, and
    printing it again in a card labelled "snapshot" is the duplication this
    page is defined against.
    """

    snapshot: str | None = None
    coverage: GithubAnalysisCoverage = Field(default_factory=GithubAnalysisCoverage)
    top_strengths: list[GithubOverviewStrength] = Field(default_factory=list)
    top_risks: list[GithubOverviewRisk] = Field(default_factory=list)
    top_recommendations: list[GithubOverviewRecommendation] = Field(default_factory=list)
    documentation_gaps: list[GithubDocumentationGapItem] = Field(default_factory=list)
    #: ONE community-activity state for the whole page.
    #: "no_community_evidence" | "community_evidence"
    community_state: str = "no_community_evidence"


# ---------------------------------------------------------------------------
# Repository -- technical
# ---------------------------------------------------------------------------


class GithubSystemComponent(BaseModel):
    """A project area read as a SYSTEM COMPONENT: what it is responsible for
    and what implements it. `responsibility` and `technologies` are absent
    for results generated before repo-v4, and the component then renders as
    the name and description it always had."""

    name: str
    responsibility: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    evidence: list[GithubPageEvidenceRef] = Field(default_factory=list)


class GithubTechnologyRoleItem(BaseModel):
    """A technology and the job it does here.

    `role` is None when the analysed documentation never said what the
    technology is for. The UI then shows the bare name -- inventing a
    purpose for a name found in a dependency list would be exactly the
    fabricated depth this pass exists to remove."""

    name: str
    role: str | None = None
    #: "frontend" | "backend" | "data" | "ai" | "infrastructure" |
    #: "security" | "other"
    category: str = "other"


class GithubTechnicalFinding(BaseModel):
    """The FULL technical finding, with everything the synthesis produced.
    Repository is the page that carries depth, so this type -- unlike the
    Overview's -- holds the whole explanation."""

    finding_id: str
    title: str
    explanation: str
    impact: str | None = None
    affected_area: str | None = None
    importance: str = "unranked"
    category: str | None = None
    finding_type: str = TYPE_ENGINEERING_RISK
    provenance: str = PROVENANCE_REPOSITORY
    evidence: list[GithubPageEvidenceRef] = Field(default_factory=list)


class GithubDocumentContribution(BaseModel):
    """One analyzed document and what it contributes to understanding the
    project. `contributes` is a deterministic statement derived from the
    document's CATEGORY -- never a summary of content the analysis did not
    read in full."""

    path: str
    title: str
    category: str
    contributes: str
    truncated: bool = False
    url: str | None = None


class GithubRepositoryView(BaseModel):
    """The reviewer's page. Everything here is either narrative the synthesis
    produced or a deterministic fact about the collected documents."""

    project_understanding: str | None = None
    architecture_summary: str | None = None
    data_flow_summary: str | None = None
    api_summary: str | None = None
    api_capabilities: list[str] = Field(default_factory=list)
    deployment_summary: str | None = None
    documentation_summary: str | None = None
    components: list[GithubSystemComponent] = Field(default_factory=list)
    technology_roles: list[GithubTechnologyRoleItem] = Field(default_factory=list)
    documents: list[GithubDocumentContribution] = Field(default_factory=list)
    #: Documentation absences belong HERE on this page, under coverage --
    #: never duplicated into the improvement inventory below.
    documentation_gaps: list[GithubDocumentationGapItem] = Field(default_factory=list)
    strengths: list[GithubTechnicalFinding] = Field(default_factory=list)
    #: Engineering risks and observations ONLY. Documentation gaps are
    #: excluded by construction so the same absence is not printed twice on
    #: one page in two different framings.
    improvements: list[GithubTechnicalFinding] = Field(default_factory=list)
    #: What the analysed evidence could not establish. Stated as a limit of
    #: the analysis, never as a defect of the repository.
    unestablished: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Problems -- diagnostic
# ---------------------------------------------------------------------------


class GithubProblemSummary(BaseModel):
    community_reported: int = 0
    repository_risks: int = 0
    documentation_gaps: int = 0
    has_community_evidence: bool = False


class GithubProblemItem(BaseModel):
    """The full diagnostic card. This is the ONE place a problem is stated in
    full -- Overview carries a one-line impact, Requests carries only the
    action, and Repository carries engineering risks under a technical
    framing."""

    problem_id: str
    title: str
    summary: str
    impact: str | None = None
    severity: str = "unranked"
    category: str | None = None
    affected_area: str | None = None
    provenance: str = PROVENANCE_REPOSITORY
    finding_type: str = TYPE_ENGINEERING_RISK
    #: One short action, never the whole Requests card. Present only when a
    #: recommendation actually addressed this problem.
    next_action: str | None = None
    evidence: list[GithubPageEvidenceRef] = Field(default_factory=list)


class GithubProblemsView(BaseModel):
    summary: GithubProblemSummary = Field(default_factory=GithubProblemSummary)
    community_problems: list[GithubProblemItem] = Field(default_factory=list)
    repository_risks: list[GithubProblemItem] = Field(default_factory=list)
    #: Kept SEPARATE from repository_risks on purpose. Visually equating a
    #: missing CONTRIBUTING.md with a runtime failure mode is the single most
    #: misleading thing this page could do.
    documentation_gaps: list[GithubDocumentationGapItem] = Field(default_factory=list)
    has_community_evidence: bool = False


# ---------------------------------------------------------------------------
# Requests -- demand
# ---------------------------------------------------------------------------


class GithubDemandSummary(BaseModel):
    feature_requests: int = 0
    suggestions: int = 0
    questions: int = 0
    has_community_demand: bool = False


class GithubDemandItem(BaseModel):
    """Something people actually asked for. `provenance` is always
    community_reported or cross_source -- a repository-derived item can never
    appear in this list, because that would be fabricating demand."""

    demand_id: str
    title: str
    summary: str
    #: "feature_request" | "suggestion" | "question"
    demand_type: str = "feature_request"
    priority: str = "unranked"
    affected_area: str | None = None
    provenance: str = PROVENANCE_COMMUNITY
    evidence: list[GithubPageEvidenceRef] = Field(default_factory=list)


class GithubOpportunityItem(BaseModel):
    """InsightForge's own suggestion, framed as a DECISION rather than as a
    complaint: what to do, how much it costs, what improves.

    Always secondary to real demand, always capped, and always labelled
    repository-derived. No user asked for these."""

    opportunity_id: str
    action: str
    priority: str = "unranked"
    expected_impact: str | None = None
    #: "low" | "medium" | "high" | None. A broad label only -- an hour
    #: estimate would be precision the evidence cannot support.
    effort: str | None = None
    affected_area: str | None = None
    #: The problem this addresses, by title. Lets the reader jump to the
    #: diagnostic on Problems instead of the diagnostic being copied here.
    related_risk: str | None = None
    provenance: str = PROVENANCE_REPOSITORY
    evidence: list[GithubPageEvidenceRef] = Field(default_factory=list)


class GithubRequestsView(BaseModel):
    summary: GithubDemandSummary = Field(default_factory=GithubDemandSummary)
    feature_requests: list[GithubDemandItem] = Field(default_factory=list)
    suggestions: list[GithubDemandItem] = Field(default_factory=list)
    recurring_questions: list[GithubDemandItem] = Field(default_factory=list)
    #: The secondary fallback. Capped at MAX_OPPORTUNITIES, and further
    #: trimmed when real demand exists -- demand outranks our advice.
    opportunities: list[GithubOpportunityItem] = Field(default_factory=list)
    has_community_demand: bool = False


class GithubPageViews(BaseModel):
    """All four projections, in the payload the dashboard already fetches.

    Shipping them together is what makes navigation free: the browser holds
    one cached response and every page reads its own slice of it. No page
    triggers a request, a generation, or a GitHub call when opened."""

    overview: GithubOverviewView = Field(default_factory=GithubOverviewView)
    repository: GithubRepositoryView = Field(default_factory=GithubRepositoryView)
    problems: GithubProblemsView = Field(default_factory=GithubProblemsView)
    requests: GithubRequestsView = Field(default_factory=GithubRequestsView)
