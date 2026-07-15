from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import router as auth_router
from app.main import app


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    """Capture reset emails instead of hitting Resend."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        auth_router.email_service,
        "send_password_reset",
        lambda to, url: sent.append((to, url)),
    )
    return sent


def request_token(client, outbox) -> str:
    r = client.post("/auth/forgot", json={"email": client.user_email})
    assert r.status_code == 200
    assert len(outbox) == 1 and outbox[0][0] == client.user_email
    url = outbox[0][1]
    assert "/reset?token=" in url
    return url.split("token=")[1]


def test_forgot_unknown_email_is_silent(anon_client, outbox):
    r = anon_client.post("/auth/forgot", json={"email": "nobody@example.com"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert outbox == []  # no user, no email — but the response is identical


def test_forgot_rejects_invalid_email(anon_client):
    assert anon_client.post("/auth/forgot", json={"email": "not-an-email"}).status_code == 422


def test_reset_changes_password_and_signs_in(client, outbox):
    token = request_token(client, outbox)

    fresh = TestClient(app)
    r = fresh.post("/auth/reset", json={"token": token, "password": "new-password-456"})
    assert r.status_code == 200
    assert fresh.get("/auth/me").json()["email"] == client.user_email  # signed in

    login = TestClient(app).post
    assert login("/auth/login", json={"email": client.user_email, "password": "password-123"}).status_code == 401
    assert login("/auth/login", json={"email": client.user_email, "password": "new-password-456"}).status_code == 200


def test_reset_revokes_existing_sessions(client, outbox):
    token = request_token(client, outbox)
    assert client.get("/auth/me").status_code == 200

    TestClient(app).post("/auth/reset", json={"token": token, "password": "new-password-456"})
    # the session that requested the reset (e.g. a stolen one) is gone
    assert client.get("/auth/me").status_code == 401


def test_reset_token_is_single_use(client, outbox):
    token = request_token(client, outbox)
    fresh = TestClient(app)
    assert fresh.post("/auth/reset", json={"token": token, "password": "new-password-456"}).status_code == 200
    assert fresh.post("/auth/reset", json={"token": token, "password": "other-password-789"}).status_code == 400


def test_reset_rejects_unknown_token(anon_client):
    r = anon_client.post("/auth/reset", json={"token": "x" * 43, "password": "new-password-456"})
    assert r.status_code == 400


def test_reset_rejects_expired_token(client, outbox):
    token = request_token(client, outbox)

    from app.database.models import PasswordReset
    from app.database.session import SessionLocal

    with SessionLocal() as db:
        for row in db.query(PasswordReset).all():
            row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    r = TestClient(app).post("/auth/reset", json={"token": token, "password": "new-password-456"})
    assert r.status_code == 400
    # old password still works
    assert client.post("/auth/login", json={"email": client.user_email, "password": "password-123"}).status_code == 200
