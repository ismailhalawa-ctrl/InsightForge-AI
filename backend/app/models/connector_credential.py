import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, LargeBinary, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import ConnectorCredentialType

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")

CREDENTIAL_VALIDATION_STATUS_MAX_LENGTH = 32


class ConnectorCredential(Base):
    """An encrypted secret (e.g. a GitHub personal access token) belonging to
    exactly one user's SourceConnection. `nonce`/`ciphertext` are only ever
    produced or consumed by app.core.credential_vault.CredentialVault using
    authenticated encryption (AES-256-GCM) -- this row never holds plaintext,
    and no API response, log line, or repr() of this class ever includes
    these two columns.

    Deleting the owning SourceConnection cascades here (a credential has no
    meaning without its connection), but that never touches SourceDataset/
    SourceRecord/AnalysisJob history: SourceDataset.source_connection_id and
    AnalysisJob's dataset link are their own separate ON DELETE SET NULL
    foreign keys, so prior collected records and analysis results survive a
    credential (or whole connection) deletion untouched.
    """

    __tablename__ = "connector_credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_connections.id", ondelete="CASCADE"), unique=True
    )

    credential_type: Mapped[ConnectorCredentialType] = mapped_column(
        Enum(ConnectorCredentialType, native_enum=False, length=32, validate_strings=True)
    )
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)

    # Best-effort, sanitized: a bounded list of scope names (e.g. "repo",
    # "public_repo") parsed from GitHub's own X-OAuth-Scopes response header
    # when present -- never the token itself, never a raw header dump.
    validated_scopes: Mapped[list | None] = mapped_column(_JSONVariant, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_validation_status: Mapped[str | None] = mapped_column(
        String(CREDENTIAL_VALIDATION_STATUS_MAX_LENGTH), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"ConnectorCredential(id={self.id!r}, credential_type={self.credential_type!r})"
