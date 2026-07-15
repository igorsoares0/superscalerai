import hashlib
import hmac
import json
import time
import uuid

import pytest

from app.core.config import settings
from app.services import billing

SECRET = "pdl_ntfset_test_secret"

BASIC = 250  # monthly allowance used in test events


@pytest.fixture(autouse=True)
def webhook_secret():
    old = settings.paddle_webhook_secret
    settings.paddle_webhook_secret = SECRET
    yield
    settings.paddle_webhook_secret = old


def sign(body: bytes, ts: int | None = None, secret: str = SECRET) -> str:
    ts = int(time.time()) if ts is None else ts
    mac = hmac.new(secret.encode(), f"{ts}:".encode() + body, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={mac}"


def completed_event(
    user_id: str,
    txn: str | None = None,
    plan: str = "basic",
    credits: int = BASIC,
    app: str = "superscaler",
    subscription_id: str | None = None,
) -> dict:
    # subscription ids are globally unique at Paddle; tests share one dev.db
    subscription_id = subscription_id or f"sub_{uuid.uuid4().hex[:26]}"
    return {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "event_type": "transaction.completed",
        "data": {
            "id": txn or f"txn_{uuid.uuid4().hex[:26]}",
            "subscription_id": subscription_id,
            "custom_data": {"app": app, "user_id": user_id},
            "items": [
                {
                    "quantity": 1,
                    "price": {
                        "id": "pri_test",
                        "custom_data": {"app": app, "plan": plan, "credits": credits},
                    },
                }
            ],
            "billing_period": {
                "starts_at": "2026-07-14T00:00:00Z",
                "ends_at": "2026-08-14T00:00:00Z",
            },
            "details": {"totals": {"total": "1200", "grand_total": "1200", "currency_code": "USD"}},
        },
    }


def canceled_event(user_id: str, subscription_id: str) -> dict:
    return {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "event_type": "subscription.canceled",
        "data": {
            "id": subscription_id,
            "custom_data": {"app": "superscaler", "user_id": user_id},
        },
    }


def post_webhook(client, event: dict, header: str | None = "auto"):
    body = json.dumps(event).encode()
    headers = {}
    if header == "auto":
        headers["Paddle-Signature"] = sign(body)
    elif header is not None:
        headers["Paddle-Signature"] = header
    return client.post("/billing/webhook/paddle", content=body, headers=headers)


def user_id_of(client) -> str:
    return client.get("/auth/me").json()["id"]


# ---- plans catalog ----


def test_plans_requires_auth(anon_client):
    assert anon_client.get("/billing/plans").status_code == 401


def test_plans_listed(client):
    body = client.get("/billing/plans").json()
    assert body["environment"] == "sandbox"
    assert [p["slug"] for p in body["plans"]] == ["basic", "pro"]
    for plan in body["plans"]:
        assert plan["price_id"].startswith("pri_")
        assert plan["credits"] > 0 and plan["amount"] > 0
    assert body["current"] == {"plan": None, "renews_at": None}


# ---- webhook signature ----


def test_webhook_rejects_missing_signature(client):
    r = post_webhook(client, completed_event(user_id_of(client)), header=None)
    assert r.status_code == 401


def test_webhook_rejects_bad_signature(client):
    event = completed_event(user_id_of(client))
    body = json.dumps(event).encode()
    r = post_webhook(client, event, header=sign(body, secret="wrong-secret"))
    assert r.status_code == 401


def test_webhook_rejects_stale_timestamp(client):
    event = completed_event(user_id_of(client))
    body = json.dumps(event).encode()
    stale = int(time.time()) - settings.paddle_webhook_max_age_seconds - 60
    r = post_webhook(client, event, header=sign(body, ts=stale))
    assert r.status_code == 401


def test_signature_tampered_body_fails():
    body = b'{"a": 1}'
    header = sign(body)
    assert billing.verify_paddle_signature(body, header, SECRET, 300)
    assert not billing.verify_paddle_signature(b'{"a": 2}', header, SECRET, 300)


# ---- subscription lifecycle ----


def test_first_charge_activates_plan(client):
    uid = user_id_of(client)
    r = post_webhook(client, completed_event(uid))
    assert r.status_code == 200 and r.json()["status"] == "renewed"

    credits = client.get("/credits").json()
    assert credits["balance"] == BASIC  # reset, not signup bonus + allowance
    renewal = [e for e in credits["ledger"] if e["reason"] == "plan_renewal"]
    assert len(renewal) == 1 and renewal[0]["delta"] == BASIC - 3  # bonus absorbed

    current = client.get("/billing/plans").json()["current"]
    assert current["plan"] == "basic"
    assert current["renews_at"].startswith("2026-08-14")


def test_renewal_resets_balance_instead_of_adding(client):
    uid = user_id_of(client)
    post_webhook(client, completed_event(uid))
    # spend part of the month's credits, then renew
    from app.database.models import User
    from app.database.session import SessionLocal

    with SessionLocal() as db:
        user = db.get(User, uid)
        user.credits = 40
        db.commit()

    assert post_webhook(client, completed_event(uid)).json()["status"] == "renewed"
    assert client.get("/credits").json()["balance"] == BASIC  # 250, not 290


def test_duplicate_delivery_applies_once(client):
    uid = user_id_of(client)
    event = completed_event(uid, txn="txn_dup_" + uuid.uuid4().hex[:8])
    assert post_webhook(client, event).json()["status"] == "renewed"
    assert post_webhook(client, event).json()["status"] == "duplicate"
    ledger = client.get("/credits").json()["ledger"]
    assert len([e for e in ledger if e["reason"] == "plan_renewal"]) == 1


def test_cancel_expires_credits_and_plan(client):
    uid = user_id_of(client)
    sub = f"sub_{uuid.uuid4().hex[:26]}"
    post_webhook(client, completed_event(uid, subscription_id=sub))
    r = post_webhook(client, canceled_event(uid, subscription_id=sub))
    assert r.status_code == 200 and r.json()["status"] == "canceled"

    credits = client.get("/credits").json()
    assert credits["balance"] == 0
    expired = [e for e in credits["ledger"] if e["reason"] == "plan_expired"]
    assert len(expired) == 1 and expired[0]["delta"] == -BASIC
    assert client.get("/billing/plans").json()["current"]["plan"] is None


def test_canceling_untracked_subscription_keeps_plan(client):
    """An orphaned subscription (e.g. from a checkout whose webhook failed)
    being canceled must not expire the user's current plan."""
    uid = user_id_of(client)
    current = f"sub_{uuid.uuid4().hex[:26]}"
    orphan = f"sub_{uuid.uuid4().hex[:26]}"
    post_webhook(client, completed_event(uid, subscription_id=current))

    r = post_webhook(client, canceled_event(uid, subscription_id=orphan))
    assert r.status_code == 200 and r.json()["status"] == "ignored"
    assert client.get("/credits").json()["balance"] == BASIC
    assert client.get("/billing/plans").json()["current"]["plan"] == "basic"


def test_other_apps_events_ignored(client):
    uid = user_id_of(client)
    r = post_webhook(client, completed_event(uid, app="someother"))
    assert r.status_code == 200 and r.json()["status"] == "ignored"
    assert client.get("/credits").json()["balance"] == 3


def test_other_event_types_acknowledged(client):
    event = completed_event(user_id_of(client))
    event["event_type"] = "transaction.created"
    r = post_webhook(client, event)
    assert r.status_code == 200 and r.json()["status"] == "ignored"
    assert client.get("/credits").json()["balance"] == 3
