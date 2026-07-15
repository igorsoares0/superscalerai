"""Billing endpoints: plan catalog for the frontend and the Paddle webhook."""

import json
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
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
        },
    }


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
        user.plan_cancels_at = _parse_dt(effective) or user.plan_renews_at
        db.commit()
        logger.info(
            "subscription %s cancels at %s", user.paddle_subscription_id, user.plan_cancels_at
        )
    return {
        "plan": user.plan,
        "cancels_at": user.plan_cancels_at.isoformat() if user.plan_cancels_at else None,
    }


def _parse_dt(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _handle_transaction_completed(db: Session, data: dict) -> str:
    transaction_id = data.get("id")
    custom = data.get("custom_data") or {}
    user = db.get(User, custom.get("user_id") or "")
    if user is None or not transaction_id:
        logger.warning("paddle webhook: no user for transaction %s", transaction_id)
        return "ignored"

    plan = billing.plan_in_transaction(data)
    if plan is None:
        logger.warning("paddle webhook: no plan items on %s", transaction_id)
        return "ignored"
    plan_slug, credits = plan

    totals = (data.get("details") or {}).get("totals") or {}
    try:
        amount = int(totals.get("grand_total") or totals.get("total") or 0)
    except (TypeError, ValueError):
        amount = 0
    currency = totals.get("currency_code") or "USD"
    renews_at = _parse_dt((data.get("billing_period") or {}).get("ends_at"))

    try:
        applied = billing.apply_renewal(
            db,
            user,
            transaction_id,
            plan_slug,
            credits,
            amount,
            currency,
            data.get("subscription_id"),
            renews_at,
        )
        db.commit()
    except IntegrityError:  # concurrent duplicate delivery
        db.rollback()
        applied = False
    if applied:
        logger.info(
            "paddle webhook: %s renewed to plan %s (%d credits, %s)",
            user.id,
            plan_slug,
            credits,
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

    data = event.get("data") or {}
    custom = data.get("custom_data") or {}
    if custom.get("app") != billing.CUSTOM_DATA_APP:
        return {"status": "ignored"}  # another app on the shared Paddle account

    # Non-2xx makes Paddle retry; events we don't act on are acknowledged.
    event_type = event.get("event_type")
    if event_type == "transaction.completed":
        return {"status": _handle_transaction_completed(db, data)}
    if event_type == "subscription.canceled":
        return {"status": _handle_subscription_canceled(db, data)}
    return {"status": "ignored"}
