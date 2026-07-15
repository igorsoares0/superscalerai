"""Paddle billing: monthly credit plans, webhook signature verification, and
idempotent renewal processing (one Payment row per Paddle transaction).

Plan credits DON'T accumulate: every settled subscription charge (first
payment and each renewal) resets the balance to the plan's monthly allowance.
The allowance is read from the Paddle price's custom_data at webhook time, so
the PLANS list below is only for display and checkout wiring.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import CreditLedger, Payment, User

PADDLE_API_BASE = {
    "sandbox": "https://sandbox-api.paddle.com",
    "production": "https://api.paddle.com",
}

# The Paddle sandbox account is shared with other apps; every price and
# checkout we own is tagged with this in custom_data so the webhook can
# ignore everything else.
CUSTOM_DATA_APP = "superscaler"


@dataclass(frozen=True)
class Plan:
    price_id: str
    slug: str
    name: str
    credits: int  # monthly allowance
    amount: int  # cents per month
    currency: str = "USD"


# Sandbox catalog (product pro_01kxhfxj722hfs6bqpfhcs46d1); production gets
# its own price ids via config when we set the live account up.
PLANS = [
    Plan("pri_01kxhgnzn8v3hmx52s8fc8dmzn", "basic", "Basic", 250, 1200),
    Plan("pri_01kxhgnzse29n9pg7sz5y74jmp", "pro", "Pro", 1000, 3900),
]


def signature_failure_reason(
    raw_body: bytes, header: str | None, secret: str, max_age_seconds: int
) -> str | None:
    """None when the signature is valid, otherwise a log-safe reason (never
    includes the secret or hashes).

    Paddle-Signature header: ``ts=<unix>;h1=<hex hmac>``. h1 can appear more
    than once while an endpoint secret is being rotated. The signed payload
    is ``{ts}:{raw_body}`` with the endpoint secret as HMAC key."""
    if not secret:
        return "PADDLE_WEBHOOK_SECRET is not configured"
    if not header:
        return "missing Paddle-Signature header"
    ts: str | None = None
    hashes: list[str] = []
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == "ts":
            ts = value
        elif key == "h1":
            hashes.append(value)
    if ts is None or not ts.isdigit() or not hashes:
        return "malformed Paddle-Signature header"
    skew = time.time() - int(ts)
    if abs(skew) > max_age_seconds:  # replay protection
        return f"timestamp outside tolerance (skew {skew:+.0f}s)"
    expected = hmac.new(
        secret.encode(), f"{ts}:".encode() + raw_body, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, h) for h in hashes):
        return "hmac mismatch (wrong secret or altered body)"
    return None


def verify_paddle_signature(
    raw_body: bytes, header: str | None, secret: str, max_age_seconds: int
) -> bool:
    return signature_failure_reason(raw_body, header, secret, max_age_seconds) is None


def plan_in_transaction(data: dict) -> tuple[str, int] | None:
    """(plan slug, monthly credits) from the first line item tagged as ours,
    read from the price's custom_data. None when no item is ours."""
    for item in data.get("items", []):
        custom = (item.get("price") or {}).get("custom_data") or {}
        if custom.get("app") != CUSTOM_DATA_APP:
            continue
        try:
            credits = int(custom.get("credits", 0))
        except (TypeError, ValueError):
            continue
        slug = custom.get("plan")
        if slug and credits > 0:
            return str(slug), credits
    return None


def cancel_subscription(subscription_id: str) -> str | None:
    """Ask Paddle to cancel at the end of the paid period (the user keeps
    what they paid for; the subscription.canceled webhook expires the credits
    on the effective date). Returns the ISO effective date — None when Paddle
    canceled immediately instead of scheduling. Raises httpx.HTTPError on API
    failure; callers decide how to answer the user."""
    base = PADDLE_API_BASE[settings.paddle_environment]
    r = httpx.post(
        f"{base}/subscriptions/{subscription_id}/cancel",
        headers={"Authorization": f"Bearer {settings.paddle_api_key}"},
        json={"effective_from": "next_billing_period"},
        timeout=15,
    )
    r.raise_for_status()
    change = (r.json().get("data") or {}).get("scheduled_change") or {}
    return change.get("effective_at")


def change_subscription_plan(subscription_id: str, price_id: str, upgrade: bool) -> None:
    """Swap the subscription to another price. Upgrades charge the prorated
    difference right away — the resulting transaction.completed webhook flips
    the plan and resets credits. Downgrades bill nothing until the next
    renewal, so the user keeps what they paid for; the renewal transaction
    carries the new price and resets credits then. Raises httpx.HTTPError on
    API failure."""
    base = PADDLE_API_BASE[settings.paddle_environment]
    r = httpx.patch(
        f"{base}/subscriptions/{subscription_id}",
        headers={"Authorization": f"Bearer {settings.paddle_api_key}"},
        json={
            "items": [{"price_id": price_id, "quantity": 1}],
            "proration_billing_mode": (
                "prorated_immediately" if upgrade else "full_next_billing_period"
            ),
        },
        timeout=15,
    )
    r.raise_for_status()


def apply_renewal(
    db: Session,
    user: User,
    transaction_id: str,
    plan_slug: str,
    credits: int,
    amount: int,
    currency: str,
    subscription_id: str | None,
    renews_at: datetime | None,
) -> bool:
    """Settle one subscription charge exactly once: reset the balance to the
    plan's monthly allowance (credits expire, they don't accumulate) and
    stamp the user's plan state. Returns False when this transaction was
    already processed. Concurrent duplicate deliveries are caught by the
    unique constraint on provider_transaction_id — callers treat
    IntegrityError on commit as a duplicate."""
    already = db.scalar(
        select(Payment.id).where(Payment.provider_transaction_id == transaction_id)
    )
    if already is not None:
        return False
    payment = Payment(
        user_id=user.id,
        credits=credits,
        amount=amount,
        currency=currency,
        provider="paddle",
        provider_transaction_id=transaction_id,
    )
    db.add(payment)
    db.flush()
    delta = credits - user.credits
    user.credits = credits
    user.plan = plan_slug
    user.paddle_subscription_id = subscription_id
    user.plan_renews_at = renews_at
    user.plan_cancels_at = None  # a settled charge means the plan is live
    user.plan_pending = None  # the charge's price IS the plan now
    if delta != 0:
        db.add(
            CreditLedger(
                user_id=user.id, delta=delta, reason="plan_renewal", payment_id=payment.id
            )
        )
    return True


def expire_subscription(db: Session, user: User) -> None:
    """Subscription ended: plan credits expire with it. Idempotent by
    construction — a user with no plan and no credits is a no-op."""
    if user.credits > 0:
        db.add(CreditLedger(user_id=user.id, delta=-user.credits, reason="plan_expired"))
        user.credits = 0
    user.plan = None
    user.paddle_subscription_id = None
    user.plan_renews_at = None
    user.plan_cancels_at = None
    user.plan_pending = None
