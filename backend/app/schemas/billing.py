from datetime import datetime

from pydantic import BaseModel

from app.models.enums import UserPlan


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class PortalSessionResponse(BaseModel):
    portal_url: str


class BillingStatusResponse(BaseModel):
    plan: UserPlan
    billing_configured: bool
    status: str | None
    current_period_end: datetime | None
