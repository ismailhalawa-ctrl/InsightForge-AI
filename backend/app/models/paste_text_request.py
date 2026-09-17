import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import PasteTextSplitMode

PASTE_TEXT_TITLE_MAX_CHARS = 255


class PasteTextRequest(Base):
    """The immutable input for one pasted-text dataset (Sprint 23), created by
    POST /api/v1/sources/datasets/text and referenced afterward only as the
    opaque `reference` string PasteTextConnector resolves it from (see
    GitHubAnalysisRequest's docstring for why this per-run-config-row pattern
    exists: a SourceConnector only ever receives `db`, `settings`, and this
    one reference, never the calling user or dataset object directly).

    Unlike GitHubAnalysisRequest, this table holds the actual source content
    (not just collection options) because pasted text has no external API to
    re-fetch it from later -- `text` IS the source, bounded at the API layer
    by settings.SOURCE_INPUT_MAX_LENGTH before this row is ever created.
    """

    __tablename__ = "paste_text_requests"
    __table_args__ = (Index("ix_paste_text_request_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )

    title: Mapped[str | None] = mapped_column(String(PASTE_TEXT_TITLE_MAX_CHARS), nullable=True)
    split_mode: Mapped[PasteTextSplitMode] = mapped_column(
        Enum(PasteTextSplitMode, native_enum=False, length=16, validate_strings=True)
    )
    text: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
