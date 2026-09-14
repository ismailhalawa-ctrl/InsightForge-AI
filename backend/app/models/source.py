import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import (
    CollectionState,
    DatasetType,
    RecordType,
    SourceConnectionStatus,
    SourceDatasetStatus,
    SourceType,
)

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")

SOURCE_RECORD_TEXT_MAX_LENGTH = 20000
SOURCE_METADATA_MAX_BYTES = 8192


class SourceConnection(Base):
    """A user's configured link to an external source (e.g. a connected
    GitHub organization or app store listing). Never stores credentials
    directly -- no credential vault abstraction exists yet, so connectors
    requiring authentication read it from application settings, not from a
    per-user persisted secret. `configuration` is strictly non-secret and
    bounded (see SOURCE_METADATA_MAX_BYTES).
    """

    __tablename__ = "source_connections"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_type", "external_account_id", name="uq_source_connection_identity"
        ),
        Index("ix_source_connection_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False, length=32, validate_strings=True)
    )
    display_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[SourceConnectionStatus] = mapped_column(
        Enum(SourceConnectionStatus, native_enum=False, length=16, validate_strings=True),
        default=SourceConnectionStatus.active,
    )
    external_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    configuration: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    capabilities: Mapped[dict] = mapped_column(_JSONVariant, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SourceDataset(Base):
    """One collectible unit within a source: a single YouTube video's
    comments, a GitHub repository's issues, an app's store reviews. Analysis
    jobs target a dataset rather than a raw source reference directly, so
    the same dataset can be re-analyzed, checkpointed, and deduplicated
    across multiple jobs without re-resolving the source reference each time.
    """

    __tablename__ = "source_datasets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_type", "external_id", name="uq_source_dataset_identity"
        ),
        Index("ix_source_dataset_user_id", "user_id"),
        Index("ix_source_dataset_connection_id", "source_connection_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_connections.id", ondelete="SET NULL"), nullable=True
    )

    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False, length=32, validate_strings=True)
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dataset_type: Mapped[DatasetType] = mapped_column(
        Enum(DatasetType, native_enum=False, length=32, validate_strings=True)
    )
    display_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    dataset_metadata: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    status: Mapped[SourceDatasetStatus] = mapped_column(
        Enum(SourceDatasetStatus, native_enum=False, length=16, validate_strings=True),
        default=SourceDatasetStatus.active,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SourceRecord(Base):
    """One normalized unit of collected content (a comment, review, ticket,
    issue) belonging to a SourceDataset. `original_text` is the authoritative
    text for this record going forward -- source-specific cache tables
    (e.g. YouTubeComment) may still exist for a given connector's own TTL/
    dedup needs, but generic processing and evidence only ever read from
    here. Bounded to SOURCE_RECORD_TEXT_MAX_LENGTH so a single pathological
    record can never dominate storage or downstream processing cost.
    """

    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("dataset_id", "source_key", name="uq_source_record_dataset_key"),
        Index("ix_source_record_dataset_id", "dataset_id"),
        Index("ix_source_record_parent_key", "dataset_id", "parent_source_key"),
        Index("ix_source_record_content_hash", "dataset_id", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_datasets.id", ondelete="CASCADE")
    )

    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False, length=32, validate_strings=True)
    )
    source_key: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    record_type: Mapped[RecordType] = mapped_column(
        Enum(RecordType, native_enum=False, length=32, validate_strings=True)
    )

    parent_source_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thread_source_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    original_text: Mapped[str] = mapped_column(String(SOURCE_RECORD_TEXT_MAX_LENGTH))
    normalized_text: Mapped[str | None] = mapped_column(
        String(SOURCE_RECORD_TEXT_MAX_LENGTH), nullable=True
    )

    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    engagement: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    record_metadata: Mapped[dict] = mapped_column(_JSONVariant, default=dict)

    content_hash: Mapped[str] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CollectionCheckpoint(Base):
    """Resumable collection progress for one (dataset, connector) pair.

    Distinct from AnalysisJob.last_checkpoint: a job's checkpoint tracks that
    job's own analysis progress, while this tracks the dataset's collection
    state independent of any specific job -- so a second job against the
    same dataset can detect that collection already reached a given cursor
    without re-deriving it from job history.
    """

    __tablename__ = "collection_checkpoints"
    __table_args__ = (
        UniqueConstraint("dataset_id", "connector_name", name="uq_checkpoint_dataset_connector"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_datasets.id", ondelete="CASCADE")
    )

    connector_name: Mapped[str] = mapped_column(String(64))
    connector_version: Mapped[str] = mapped_column(String(32))

    cursor: Mapped[dict] = mapped_column(_JSONVariant, default=dict)
    state: Mapped[CollectionState] = mapped_column(
        Enum(CollectionState, native_enum=False, length=16, validate_strings=True),
        default=CollectionState.pending,
    )
    records_collected: Mapped[int] = mapped_column(Integer, default=0)

    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
