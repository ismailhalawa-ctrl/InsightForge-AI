import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import ContactInquiryType

CONTACT_NAME_MAX_CHARS = 120
CONTACT_SUBJECT_MAX_CHARS = 150
CONTACT_MESSAGE_MAX_CHARS = 4000


class ContactMessage(Base):
    """The immutable, durable record of one public Contact Us submission
    (landing page + Settings, both reuse the same frontend form). Public
    endpoint, no auth required, so there is no user_id FK -- stored plainly
    (never rendered as HTML anywhere) so a submission is never lost even
    when CONTACT_INBOX_EMAIL is unset and no notification email is sent.
    """

    __tablename__ = "contact_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name: Mapped[str] = mapped_column(String(CONTACT_NAME_MAX_CHARS))
    email: Mapped[str] = mapped_column(String(320))
    inquiry_type: Mapped[ContactInquiryType] = mapped_column(
        Enum(ContactInquiryType, native_enum=False, length=32, validate_strings=True)
    )
    subject: Mapped[str] = mapped_column(String(CONTACT_SUBJECT_MAX_CHARS))
    message: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
