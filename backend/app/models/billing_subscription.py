import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

# Stripe's own subscription status vocabulary, stored verbatim (not
# InsightForge's UserPlan) -- the entitlement resolver
# (app/services/billing/entitlement.py) is the one place that turns this
# real, full Stripe status plus current_period_end into a Free/Pro
# decision. Storing the raw status (not just a collapsed bool) is what
# lets that resolver correctly demote a cancelled/past_due/unpaid
# subscription back to Free.
STRIPE_SUBSCRIPTION_STATUSES = (
    "active",
    "trialing",
    "past_due",
    "canceled",
    "unpaid",
    "incomplete",
    "incomplete_expired",
    "paused",
)


class BillingSubscription(Base):
    """One row per user with a Stripe subscription (at most one active
    subscription per user). Webhooks are the only writer -- this table is
    never mutated directly from a user-facing request handler other than
    the initial insert-with-nulls at checkout-session creation time.
    """

    __tablename__ = "billing_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )

    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessedWebhookEvent(Base):
    """Idempotency guard for Stripe webhooks -- Stripe explicitly documents
    that the same event can be delivered more than once, so every handler
    checks this table (by Stripe's own event.id) before acting, and records
    itself here afterward. No user_id -- this is delivery-plumbing, not
    user data."""

    __tablename__ = "processed_webhook_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
