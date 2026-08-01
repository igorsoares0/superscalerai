import uuid

import httpx
import pytest

from app.database.models import CreditLedger, ImageRecord, Job, Payment, User
from app.database.session import SessionLocal
from app.services import billing
from tests.conftest import png_bytes
from tests.test_billing import BASIC, completed_event, new_sub, post_webhook, user_id_of
from tests.test_billing import webhook_secret  # noqa: F401 — autouse fixture, used by pytest

PASSWORD = "password-123"


@pytest.fixture
def paddle_cancel(monkeypatch):
    """Capture the cancel call instead of hitting Paddle."""
    calls = []

    def fake(subscription_id, immediately=False):
        calls.append((subscription_id, immediately))
        return None

    monkeypatch.setattr(billing, "cancel_subscription", fake)
    return calls


def delete(client, password: str = PASSWORD):
    return client.post("/auth/delete", json={"password": password})


def with_an_image(client) -> str:
    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    assert r.status_code == 201
    return r.json()["id"]


def test_wrong_password_deletes_nothing(client):
    with_an_image(client)
    assert delete(client, "not-my-password").status_code == 401
    assert client.get("/auth/me").status_code == 200
    assert len(client.get("/images").json()) == 1


def test_delete_removes_the_content_and_ends_the_session(client):
    uid = user_id_of(client)
    with_an_image(client)

    assert delete(client).status_code == 200
    assert client.get("/auth/me").status_code == 401  # session gone

    with SessionLocal() as db:
        assert db.scalars(select_images(uid)).all() == []
        user = db.get(User, uid)
        assert user.deleted_at is not None
        assert user.email.endswith("@deleted.invalid") and user.password_hash == ""
        assert user.credits == 0


def select_images(user_id: str):
    from sqlalchemy import select

    return select(ImageRecord).where(ImageRecord.user_id == user_id)


def test_the_money_trail_survives(client, paddle_cancel):
    """payments is retained for tax and credit_ledger is append-only — both FK
    to users.id, which is why the row is scrubbed instead of deleted."""
    uid = user_id_of(client)
    post_webhook(client, completed_event(uid, subscription_id=new_sub()))

    assert delete(client).status_code == 200

    with SessionLocal() as db:
        from sqlalchemy import select

        assert db.scalar(select(Payment).where(Payment.user_id == uid)) is not None
        ledger = db.scalars(select(CreditLedger).where(CreditLedger.user_id == uid)).all()
        assert [e.reason for e in ledger if e.reason == "plan_renewal"]
        # the balance and the ledger stay consistent: zeroing is recorded
        closing = [e for e in ledger if e.reason == "account_deleted"]
        assert len(closing) == 1 and closing[0].delta == -BASIC


def test_delete_cancels_the_subscription_immediately(client, paddle_cancel):
    """An account nobody can log into must not keep being billed."""
    uid = user_id_of(client)
    sub = new_sub()
    post_webhook(client, completed_event(uid, subscription_id=sub))

    assert delete(client).status_code == 200
    assert paddle_cancel == [(sub, True)]


def test_paddle_failure_aborts_the_whole_deletion(client, monkeypatch):
    """Deleting locally while the card keeps being charged is the worst
    outcome available — nothing may be committed."""
    uid = user_id_of(client)
    post_webhook(client, completed_event(uid, subscription_id=new_sub()))
    with_an_image(client)

    def boom(subscription_id, immediately=False):
        raise httpx.HTTPError("paddle down")

    monkeypatch.setattr(billing, "cancel_subscription", boom)

    assert delete(client).status_code == 502
    assert client.get("/auth/me").status_code == 200
    assert len(client.get("/images").json()) == 1
    with SessionLocal() as db:
        assert db.get(User, uid).deleted_at is None


def test_jobs_go_but_their_ledger_entries_stay(client, paddle_cancel):
    uid = user_id_of(client)
    image_id = with_an_image(client)
    with SessionLocal() as db:  # a finished job, without running the pipeline
        db.add(
            Job(
                id=str(uuid.uuid4()),
                user_id=uid,
                image_id=image_id,
                preset="portrait",
                status="completed",
                credits_cost=2,
            )
        )
        db.flush()
        job = db.scalars(select_jobs(uid)).one()
        db.add(CreditLedger(user_id=uid, delta=-2, reason="job_debit", job_id=job.id))
        db.commit()

    assert delete(client).status_code == 200

    with SessionLocal() as db:
        from sqlalchemy import select

        assert db.scalars(select_jobs(uid)).all() == []
        debit = db.scalar(
            select(CreditLedger).where(
                CreditLedger.user_id == uid, CreditLedger.reason == "job_debit"
            )
        )
        assert debit is not None and debit.job_id is None  # orphaned, not deleted


def select_jobs(user_id: str):
    from sqlalchemy import select

    return select(Job).where(Job.user_id == user_id)


def test_the_freed_email_can_register_again(client, paddle_cancel):
    email = client.user_email
    assert delete(client).status_code == 200
    assert client.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code == 201


def test_a_leftover_session_stops_working(client, paddle_cancel):
    """Deletion drops every session, but the row outlives the person — a token
    that somehow survives must not resolve to a logged-in user."""
    uid = user_id_of(client)
    cookie = client.cookies.get("session")
    assert delete(client).status_code == 200

    from app.auth import service

    with SessionLocal() as db:
        service.create_session(db, uid)  # forge one for a deleted account
        db.commit()
    client.cookies.set("session", cookie)
    assert client.get("/auth/me").status_code == 401
