"""Billing endpoints: plan catalog for the frontend and the Paddle webhook."""

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.database.models import User
from app.database.session import get_db
from app.services import billing

router = APIRouter(prefix="/billing", tags=["billing"])
logger = logging.getLogger(__name__)


@router.get("/plans")
def list_plans(user: User = Depends(get_current_user)) -> dict:
    return {
        "environment": settings.paddle_environment,
        "client_token": settings.paddle_client_token,
        "plans": [
            {
                "price_id": p.price_id,
                "slug": p.slug,
                "name": p.name,
                "credits": p.credits,
                "amount": p.amount,
                "currency": p.currency,
            }
            for p in billing.PLANS
        ],
        "current": {
            "plan": user.plan,
            "renews_at": user.plan_renews_at.isoformat() if user.plan_renews_at else None,
            "cancels_at": user.plan_cancels_at.isoformat() if user.plan_cancels_at else None,
            "pending": user.plan_pending,
        },
    }


class ChangeBody(BaseModel):
    plan: str


@router.post("/change")
def change_plan(
    body: ChangeBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Switch an active subscription to another plan. Never opens a second
    checkout — that would create a second subscription at Paddle. Upgrades
    charge the prorated difference now (webhook resets credits within
    seconds); downgrades start at the next renewal."""
    target = next((p for p in billing.PLANS if p.slug == body.plan), None)
    if target is None:
        raise HTTPException(400, "unknown plan")
    if not user.paddle_subscription_id:
        raise HTTPException(400, "no active subscription")  # new users go through checkout
    if user.plan_cancels_at is not None:
        raise HTTPException(400, "subscription is scheduled to cancel — resume it first")
    if target.slug == user.plan:
        if user.plan_pending is None:
            raise HTTPException(400, "already on this plan")
        # A downgrade was scheduled and they changed their mind. Pointing the
        # items back at the plan they're already on bills nothing now (this
        # period is paid) and renews on it — exactly "never mind".
        try:
            billing.change_subscription_plan(user.paddle_subscription_id, target.price_id, False)
        except httpx.HTTPError:
            logger.exception("paddle plan change failed for %s", user.paddle_subscription_id)
            raise HTTPException(502, "couldn't reach the payment provider, try again")
        user.plan_pending = None
        db.commit()
        logger.info("subscription %s stays on %s", user.paddle_subscription_id, target.slug)
        return {"status": "kept", "plan": target.slug}
    if target.slug == user.plan_pending:  # repeat click on a scheduled downgrade
        return {"status": "scheduled", "plan": target.slug}

    current = next((p for p in billing.PLANS if p.slug == user.plan), None)
    upgrade = current is None or target.amount > current.amount
    try:
        billing.change_subscription_plan(user.paddle_subscription_id, target.price_id, upgrade)
    except httpx.HTTPError:
        logger.exception("paddle plan change failed for %s", user.paddle_subscription_id)
        raise HTTPException(502, "couldn't reach the payment provider, try again")

    if upgrade:
        logger.info("subscription %s upgraded to %s", user.paddle_subscription_id, target.slug)
        return {"status": "upgraded", "plan": target.slug}
    user.plan_pending = target.slug
    db.commit()
    logger.info(
        "subscription %s downgrades to %s at next renewal",
        user.paddle_subscription_id,
        target.slug,
    )
    return {"status": "scheduled", "plan": target.slug}


@router.post("/cancel")
def cancel_plan(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Schedule the user's subscription to cancel at the end of the paid
    period. Idempotent: once scheduled, repeats just return the date."""
    if not user.paddle_subscription_id:
        raise HTTPException(400, "no active subscription")
    if user.plan_cancels_at is None:
        try:
            effective = billing.cancel_subscription(user.paddle_subscription_id)
        except httpx.HTTPError:
            logger.exception("paddle cancel failed for %s", user.paddle_subscription_id)
            raise HTTPException(502, "couldn't reach the payment provider, try again")
        # immediate cancels have no scheduled date; the webhook that follows
        # clears the plan either way
        user.plan_cancels_at = billing.parse_dt(effective) or user.plan_renews_at
        db.commit()
        logger.info(
            "subscription %s cancels at %s", user.paddle_subscription_id, user.plan_cancels_at
        )
    return {
        "plan": user.plan,
        "cancels_at": user.plan_cancels_at.isoformat() if user.plan_cancels_at else None,
    }


@router.post("/resume")
def resume_plan(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Undo a scheduled cancellation. Without this a mis-click costs the user
    their plan: `change_plan` refuses everything while a cancellation is
    pending, so there was no way back except waiting for the period to expire
    and subscribing again. Idempotent — with nothing scheduled it just reports
    the current state."""
    if not user.paddle_subscription_id:
        raise HTTPException(400, "no active subscription")
    if user.plan_cancels_at is not None:
        try:
            billing.resume_subscription(user.paddle_subscription_id)
        except httpx.HTTPError:
            logger.exception("paddle resume failed for %s", user.paddle_subscription_id)
            raise HTTPException(502, "couldn't reach the payment provider, try again")
        user.plan_cancels_at = None
        db.commit()
        logger.info("subscription %s resumed for %s", user.paddle_subscription_id, user.id)
    return {"plan": user.plan, "cancels_at": None}


def _handle_transaction_completed(db: Session, data: dict) -> str:
    transaction_id = data.get("id")
    custom = data.get("custom_data") or {}

    # Ownership first: on the shared Paddle account, a tagged price on the line
    # items is what makes a transaction ours.
    plan = billing.plan_in_transaction(data)
    if plan is None:
        if custom.get("app") == billing.CUSTOM_DATA_APP:  # ours, but malformed
            logger.warning("paddle webhook: no plan items on %s", transaction_id)
        return "ignored"
    plan_slug, credits = plan

    subscription_id = data.get("subscription_id")
    # custom_data is injected at checkout, so it can't be trusted to ride along
    # on later renewal transactions. Falling back to the subscription we already
    # track is what keeps a paying customer from silently losing a month of
    # credits. The lookup is exact: subscription ids are unique at Paddle.
    user = db.get(User, custom.get("user_id") or "")
    if user is None and subscription_id:
        user = db.scalar(select(User).where(User.paddle_subscription_id == subscription_id))
    if user is None or not transaction_id:
        logger.warning("paddle webhook: no user for transaction %s", transaction_id)
        return "ignored"

    totals = (data.get("details") or {}).get("totals") or {}
    try:
        amount = int(totals.get("grand_total") or totals.get("total") or 0)
    except (TypeError, ValueError):
        amount = 0
    currency = totals.get("currency_code") or "USD"
    renews_at = billing.parse_dt((data.get("billing_period") or {}).get("ends_at"))
    prorated = billing.proration_rate(data)

    try:
        applied = billing.apply_renewal(
            db,
            user,
            transaction_id,
            plan_slug,
            credits,
            amount,
            currency,
            subscription_id,
            renews_at,
            prorated,
        )
        db.commit()
    except IntegrityError:  # concurrent duplicate delivery
        db.rollback()
        applied = False
    if applied:
        logger.info(
            "paddle webhook: %s settled plan %s (%d credits%s, %s)",
            user.id,
            plan_slug,
            credits,
            "" if prorated is None else f", prorated {prorated:.3f}",
            transaction_id,
        )
    return "renewed" if applied else "duplicate"


def _handle_subscription_canceled(db: Session, data: dict) -> str:
    subscription_id = data.get("id")
    # Match strictly on the subscription we track: a canceled subscription
    # that isn't the user's current one (e.g. an orphan from a re-checkout)
    # must not expire their active plan.
    user = db.scalar(select(User).where(User.paddle_subscription_id == subscription_id))
    if user is None:
        logger.warning("paddle webhook: no user tracks canceled subscription %s", subscription_id)
        return "ignored"
    billing.expire_subscription(db, user)
    db.commit()
    logger.info("paddle webhook: subscription %s canceled for %s", subscription_id, user.id)
    return "canceled"


@router.post("/webhook/paddle")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    raw = await request.body()
    failure = billing.signature_failure_reason(
        raw,
        request.headers.get("Paddle-Signature"),
        settings.paddle_webhook_secret,
        settings.paddle_webhook_max_age_seconds,
    )
    if failure is not None:
        logger.warning("paddle webhook rejected: %s", failure)
        raise HTTPException(401, "invalid signature")

    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "invalid payload")

    # No custom_data gate here: it's injected at checkout and Paddle isn't
    # guaranteed to carry it onto the transactions it generates later. Each
    # handler decides ownership from something durable instead — the price tag
    # on the line items, or the subscription id we already track — so an event
    # from another app on the shared Paddle account still can't match.
    data = event.get("data") or {}

    # Non-2xx makes Paddle retry; events we don't act on are acknowledged.
    event_type = event.get("event_type")
    if event_type == "transaction.completed":
        return {"status": _handle_transaction_completed(db, data)}
    if event_type == "subscription.canceled":
        return {"status": _handle_subscription_canceled(db, data)}
    return {"status": "ignored"}
