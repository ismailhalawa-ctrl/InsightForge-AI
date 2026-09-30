from pydantic import BaseModel, EmailStr, Field

from app.models.contact_message import (
    CONTACT_MESSAGE_MAX_CHARS,
    CONTACT_NAME_MAX_CHARS,
    CONTACT_SUBJECT_MAX_CHARS,
)
from app.models.enums import ContactInquiryType

_CONTACT_MESSAGE_MIN_CHARS = 10


class ContactSubmitRequest(BaseModel):
    """Bounds mirror the frontend's own contactSchema exactly
    (frontend/src/lib/validation.ts) -- enforced server-side too, never
    trusting client-side validation alone."""

    name: str = Field(min_length=1, max_length=CONTACT_NAME_MAX_CHARS)
    email: EmailStr
    inquiry_type: ContactInquiryType
    subject: str = Field(min_length=1, max_length=CONTACT_SUBJECT_MAX_CHARS)
    message: str = Field(
        min_length=_CONTACT_MESSAGE_MIN_CHARS, max_length=CONTACT_MESSAGE_MAX_CHARS
    )


class ContactSubmitResponse(BaseModel):
    status: str = "sent"
    message: str = "Thanks -- your message has been received."
