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
from datetime import datetime, timezone

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

# Every plan bills monthly. Real periods run 28-31 days, so this is only the
# denominator for the fallback in proration_rate(), and FULL_PERIOD_DAYS is
# below the shortest real month so a February renewal is never mistaken for a
# partial period.
MONTH_DAYS = 30.0
FULL_PERIOD_DAYS = 27.5


def plan_allowance(slug: str | None) -> int | None:
    """Monthly credit allowance of a plan slug; None when it isn't ours."""
    plan = next((p for p in PLANS if p.slug == slug), None)
    return plan.credits if plan is not None else None


def parse_dt(value) -> datetime | None:
    """Paddle timestamps are ISO-8601 with a Z suffix. Always returns an
    aware UTC datetime so period arithmetic can't mix naive and aware."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


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


def _our_items(data: dict):
    """(line item, its price custom_data) for the items on a transaction that
    belong to this app. The price tag is the ownership signal that survives
    everywhere: unlike the checkout's custom_data, it rides on every
    transaction Paddle generates for the subscription."""
    for item in data.get("items", []):
        custom = (item.get("price") or {}).get("custom_data") or {}
        if custom.get("app") == CUSTOM_DATA_APP:
            yield item, custom


def plan_in_transaction(data: dict) -> tuple[str, int] | None:
    """(plan slug, monthly credits) from the first line item tagged as ours,
    read from the price's custom_data. None when no item is ours."""
    for _, custom in _our_items(data):
        try:
            credits = int(custom.get("credits", 0))
        except (TypeError, ValueError):
            continue
        slug = custom.get("plan")
        if slug and credits > 0:
            return str(slug), credits
    return None


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def proration_rate(data: dict) -> float | None:
    """Fraction of a billing period this charge covers, or None when it covers
    a whole one (first payment, renewal).

    Paddle prorates the CHARGE of an immediate upgrade but knows nothing about
    our credits. Granting a full monthly allowance for a few days' money is an
    arbitrage with no skill in it: upgrade on the last day of the cycle for
    cents, downgrade (free, takes effect next period), repeat every month."""
    for item, _ in _our_items(data):
        rate = _as_float((item.get("proration") or {}).get("rate"))
        if rate is None:
            continue
        return rate if 0.0 <= rate < 1.0 else None

    # No explicit rate: measure the window the charge covers. A proration's
    # billing_period starts at the moment of the change, a renewal's spans the
    # whole month.
    period = data.get("billing_period") or {}
    start, end = parse_dt(period.get("starts_at")), parse_dt(period.get("ends_at"))
    if start is not None and end is not None and end > start:
        days = (end - start).total_seconds() / 86400
        return None if days >= FULL_PERIOD_DAYS else max(0.0, days / MONTH_DAYS)

    # A plan change we can't measure at all: grant nothing now rather than a
    # free month — the next renewal settles the full allowance anyway.
    return 0.0 if data.get("origin") == "subscription_update" else None


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
    prorated: float | None = None,
) -> bool:
    """Settle one subscription charge exactly once: reset the balance to the
    plan's monthly allowance (credits expire, they don't accumulate) and
    stamp the user's plan state. Returns False when this transaction was
    already processed. Concurrent duplicate deliveries are caught by the
    unique constraint on provider_transaction_id — callers treat
    IntegrityError on commit as a duplicate.

    `prorated` (see proration_rate) marks a mid-cycle plan change: the charge
    only bought part of a period, so the grant matches it instead of resetting
    to a full allowance."""
    already = db.scalar(
        select(Payment.id).where(Payment.provider_transaction_id == transaction_id)
    )
    if already is not None:
        return False

    if prorated is None:
        granted, balance, reason = credits, credits, "plan_renewal"
    else:
        # The current plan's credits are already in the balance; the upgrade
        # only buys the DIFFERENCE in allowance, for the days that are left.
        previous = plan_allowance(user.plan) or 0
        granted = max(0, round((credits - previous) * prorated))
        balance, reason = user.credits + granted, "plan_upgrade"

    payment = Payment(
        user_id=user.id,
        credits=granted,
        amount=amount,
        currency=currency,
        provider="paddle",
        provider_transaction_id=transaction_id,
    )
    db.add(payment)
    db.flush()
    delta = balance - user.credits
    user.credits = balance
    user.plan = plan_slug
    if subscription_id:
        # Never null it out here: a one-off transaction carrying our tag has no
        # subscription_id, and dropping the link would cost the user "cancel"
        # and "change plan" AND break the fallback that finds them when a
        # renewal arrives without custom_data. expire_subscription clears it.
        user.paddle_subscription_id = subscription_id
    user.plan_renews_at = renews_at
    user.plan_cancels_at = None  # a settled charge means the plan is live
    user.plan_pending = None  # the charge's price IS the plan now
    if delta != 0:
        db.add(CreditLedger(user_id=user.id, delta=delta, reason=reason, payment_id=payment.id))
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
