from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.enums import GitHubRepositoryState, JobStatus, SourceConnectionStatus

_TOKEN_MAX_LENGTH = 255
_REPOSITORY_MAX_LENGTH = 512
_DISPLAY_NAME_MAX_LENGTH = 255


class GitHubConnectionCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=_DISPLAY_NAME_MAX_LENGTH)
    # Optional: a classic or fine-grained GitHub personal access token, used
    # only for private repositories or higher rate limits. Never echoed back
    # in any response -- see GitHubConnectionResponse.has_credential.
    token: str | None = Field(default=None, min_length=1, max_length=_TOKEN_MAX_LENGTH)


class GitHubCredentialReplaceRequest(BaseModel):
    token: str = Field(min_length=1, max_length=_TOKEN_MAX_LENGTH)


class GitHubConnectionResponse(BaseModel):
    id: UUID
    display_name: str
    status: SourceConnectionStatus
    has_credential: bool
    created_at: datetime
    updated_at: datetime
    last_synced_at: datetime | None


class GitHubConnectionListResponse(BaseModel):
    connections: list[GitHubConnectionResponse]


class GitHubConnectionTestResponse(BaseModel):
    status: str
    authenticated: bool
    scopes: list[str]


class GitHubRepositoryValidateRequest(BaseModel):
    repository: str = Field(min_length=1, max_length=_REPOSITORY_MAX_LENGTH)
    connection_id: UUID | None = None


class GitHubRepositoryMetadata(BaseModel):
    description: str
    stargazers_count: int
    open_issues_count: int
    language: str | None
    default_branch: str | None
    private: bool
    topics: list[str]
    html_url: str | None = None


class GitHubRepositoryValidateResponse(BaseModel):
    repository: str
    display_name: str
    canonical_url: str
    metadata: GitHubRepositoryMetadata


class GitHubAnalysisCreateRequest(BaseModel):
    """One GitHub analysis request.

    Date range semantics: `since` and `until` are both bounds on a record's
    own OCCURRENCE timestamp -- when the issue, pull request, comment,
    review or release was created (published, for a release) -- and both are
    inclusive. They are two ends of one concept, which they were not before
    Phase 1, when `since` was GitHub's updated-after filter and `until` was
    compared against creation time. A naive datetime is interpreted as UTC.

    `analysis_limit` omitted means "collect what this repository has": the
    job runs in all_available collection mode and paginates until GitHub is
    exhausted, cancellation, or quota stops it. A value is honoured exactly
    and remains subject to the account's plan entitlements.
    """

    repository: str = Field(min_length=1, max_length=_REPOSITORY_MAX_LENGTH)
    connection_id: UUID | None = None
    include_issues: bool = True
    include_pull_requests: bool = True
    include_comments: bool = True
    include_reviews: bool = True
    include_releases: bool = True
    # Phase 3: repository documentation (README, docs/, CONTRIBUTING...).
    # Defaults ON so the one-URL flow understands a project's own docs
    # without the user configuring anything.
    include_documents: bool = True
    state: GitHubRepositoryState = GitHubRepositoryState.all
    since: datetime | None = None
    until: datetime | None = None
    analysis_limit: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _validate_window(self) -> "GitHubAnalysisCreateRequest":
        if self.since is not None and self.until is not None:
            since = self.since if self.since.tzinfo else self.since.replace(tzinfo=UTC)
            until = self.until if self.until.tzinfo else self.until.replace(tzinfo=UTC)
            if since > until:
                raise ValueError("since must be earlier than or equal to until")
        return self

    @model_validator(mode="after")
    def _validate_something_selected(self) -> "GitHubAnalysisCreateRequest":
        """A run that includes nothing would collect nothing and then report
        itself complete, which is indistinguishable from an empty repository.
        Rejecting it up front is the only honest answer.
        """
        if not any(
            (
                self.include_issues,
                self.include_pull_requests,
                self.include_comments,
                self.include_reviews,
                self.include_releases,
                self.include_documents,
            )
        ):
            raise ValueError("Select at least one type of repository content to collect")
        return self


class GitHubAnalysisCreatedResponse(BaseModel):
    dataset_id: UUID
    analysis_request_id: UUID
    job_id: UUID
    job_status: JobStatus
    repository: str
