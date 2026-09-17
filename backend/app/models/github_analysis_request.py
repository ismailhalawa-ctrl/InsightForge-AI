import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import GitHubRepositoryState


class GitHubAnalysisRequest(Base):
    """The immutable collection configuration for one GitHub analysis run,
    created by POST /api/v1/sources/github/analyses and referenced afterward
    only as AnalysisJob.source_reference / CollectionRequest.source_reference
    (see GitHubConnector).

    Kept separate from SourceDataset -- which is keyed on the stable
    repository identity and shared across every run of the same repository
    -- because a SourceConnector only ever receives `db`, `settings`, and
    this one opaque reference string (see app/connectors/base.py); it never
    receives the calling user or a dataset object directly. Any per-run
    credential or collection-option choice must therefore be resolvable from
    the reference alone, exactly like FileImportConnector resolves its own
    FileImport row from the file import id.
    """

    __tablename__ = "github_analysis_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_connections.id", ondelete="SET NULL"), nullable=True
    )

    # Normalized "owner/repo" (lowercased -- see app/utils/github.py), the
    # same value used as SourceDataset.external_id so repeated analyses of
    # the same repository share one dataset.
    repository: Mapped[str] = mapped_column(String(255))

    include_issues: Mapped[bool] = mapped_column(Boolean, default=True)
    include_pull_requests: Mapped[bool] = mapped_column(Boolean, default=True)
    include_comments: Mapped[bool] = mapped_column(Boolean, default=True)
    include_reviews: Mapped[bool] = mapped_column(Boolean, default=True)
    include_releases: Mapped[bool] = mapped_column(Boolean, default=True)
    # Phase 3. server_default="1" so every pre-Phase-3 row reads as True --
    # those runs predate document collection, and Run Again on one should
    # pick up the new capability rather than silently opting out of it.
    include_documents: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1"
    )
    state: Mapped[GitHubRepositoryState] = mapped_column(
        Enum(GitHubRepositoryState, native_enum=False, length=16, validate_strings=True),
        default=GitHubRepositoryState.all,
    )
    since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # NULL means the user set no explicit item limit, i.e. "collect what
    # this repository has" -- carried into the job as
    # CollectionMode.all_available. Deliberately not a large sentinel
    # number, which would be indistinguishable from a user who really did
    # request exactly that many records.
    record_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
