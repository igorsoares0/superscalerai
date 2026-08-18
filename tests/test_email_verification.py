"""Email confirmation: the signup bonus is paid for a proven address, once.

The bonus is real GPU money, so before this an invented address minted 8
credits per signup and the only barrier was 3 registrations per hour per IP.
"""

import uuid
from urllib.parse import urlparse, parse_qs

import pytest
from fastapi.testclient import TestClient

from app.auth import service
from app.core.config import settings
from app.database.models import CreditLedger, EmailVerification, User
from app.database.session import SessionLocal
from app.main import app


def register(client: TestClient) -> tuple[str, str]:
    email = f"{uuid.uuid4().hex}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "password-123"})
    assert r.status_code == 201, r.text
    return email, r.json()["id"]


def token_from(outbox: list[dict]) -> str:
    """Pull the confirmation token out of the email we actually sent — the raw
    token exists nowhere else, which is the whole point of storing only its
    hash."""
    assert outbox, "no email was sent"
    link = outbox[-1]["text"].split("\n")
    url = next(line.strip() for line in link if "/verify?token=" in line)
    return parse_qs(urlparse(url).query)["token"][0]


# ---- the happy path ----


def test_registration_sends_a_link_and_pays_nothing_yet(sent_emails):
    client = TestClient(app)
    email, user_id = register(client)

    assert client.get("/credits").json()["balance"] == 0
    assert client.get("/auth/me").json()["email_verified"] is False
    assert len(sent_emails) == 1
    assert sent_emails[0]["to"] == email
    assert "confirm" in sent_emails[0]["subject"].lower()


def test_confirming_the_link_pays_the_bonus(sent_emails):
    client = TestClient(app)
    register(client)

    r = client.post("/auth/verify", json={"token": token_from(sent_emails)})
    assert r.status_code == 200, r.text
    assert r.json()["credits"] == settings.signup_bonus_credits
    assert r.json()["email_verified"] is True

    credits = client.get("/credits").json()
    assert credits["balance"] == settings.signup_bonus_credits
    bonus = [e for e in credits["ledger"] if e["reason"] == "signup_bonus"]
    assert len(bonus) == 1 and bonus[0]["delta"] == settings.signup_bonus_credits


def test_confirming_signs_you_in_from_another_browser(sent_emails):
    """The link is routinely opened somewhere with no session — a phone, a
    mail client's built-in browser. It has to work there."""
    signup = TestClient(app)
    register(signup)

    elsewhere = TestClient(app)
    assert elsewhere.get("/auth/me").status_code == 401
    r = elsewhere.post("/auth/verify", json={"token": token_from(sent_emails)})
    assert r.status_code == 200
    assert elsewhere.get("/auth/me").json()["email_verified"] is True


# ---- the bonus is paid once, for a real address ----


def test_a_replayed_link_pays_only_once(sent_emails):
    client = TestClient(app)
    register(client)
    token = token_from(sent_emails)

    assert client.post("/auth/verify", json={"token": token}).status_code == 200
    # single-use: the second click is refused outright
    assert client.post("/auth/verify", json={"token": token}).status_code == 400
    assert client.get("/credits").json()["balance"] == settings.signup_bonus_credits


def test_bonus_is_not_paid_twice_even_bypassing_the_token(sent_emails):
    """grant_signup_bonus guards the payout itself, not just the token path,
    so no future caller can double-pay by accident."""
    client = TestClient(app)
    _, user_id = register(client)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert service.grant_signup_bonus(db, user) is True
        assert service.grant_signup_bonus(db, user) is False
        db.commit()
    assert client.get("/credits").json()["balance"] == settings.signup_bonus_credits
    with SessionLocal() as db:
        entries = db.scalars(
            db.query(CreditLedger)
            .filter(CreditLedger.user_id == user_id, CreditLedger.reason == "signup_bonus")
            .statement
        ).all()
    assert len(entries) == 1


def test_unknown_and_expired_tokens_are_refused(sent_emails):
    client = TestClient(app)
    _, user_id = register(client)

    assert client.post("/auth/verify", json={"token": "x" * 32}).status_code == 400

    with SessionLocal() as db:  # push the real one past its expiry
        row = db.scalar(
            db.query(EmailVerification).filter_by(user_id=user_id).statement
        )
        row.expires_at = row.created_at.replace(year=2000)
        db.commit()
    assert client.post("/auth/verify", json={"token": token_from(sent_emails)}).status_code == 400
    assert client.get("/credits").json()["balance"] == 0


# ---- resending ----


def test_resend_issues_a_working_link_and_kills_the_old_one(sent_emails):
    client = TestClient(app)
    register(client)
    first = token_from(sent_emails)

    assert client.post("/auth/resend-verification").status_code == 200
    second = token_from(sent_emails)
    assert second != first

    # only the newest link works: an inbox with three of these shouldn't
    # depend on which one you happen to click
    assert client.post("/auth/verify", json={"token": first}).status_code == 400
    assert client.post("/auth/verify", json={"token": second}).status_code == 200


def test_resend_is_rate_limited(sent_emails, monkeypatch):
    monkeypatch.setattr(settings, "verify_resend_rate_limit", 2)
    client = TestClient(app)
    register(client)

    assert client.post("/auth/resend-verification").status_code == 200
    assert client.post("/auth/resend-verification").status_code == 200
    assert client.post("/auth/resend-verification").status_code == 429


def test_resend_requires_a_session(sent_emails):
    """No email in the body, so it can't be aimed at a stranger's inbox or
    used to probe which addresses exist."""
    assert TestClient(app).post("/auth/resend-verification").status_code == 401


def test_resend_on_a_confirmed_account_is_a_no_op(client, sent_emails):
    before = len(sent_emails)
    assert client.post("/auth/resend-verification").status_code == 200
    assert len(sent_emails) == before


# ---- what an unconfirmed account can still do ----


def test_unconfirmed_account_can_sign_in_but_not_upload(unverified_client):
    """The gate hardened on 2026-08-18: it used to be soft (upload freely,
    fail at the job for lack of credits), which meant an address nobody
    confirmed could fill the bucket with files no job would ever read.
    Signing in and looking around still works — see
    tests/test_upload_gating.py for the upload side."""
    from tests.conftest import png_bytes

    c = unverified_client
    assert c.get("/auth/me").status_code == 200
    assert c.get("/images").json() == []

    r = c.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    assert r.status_code == 403
