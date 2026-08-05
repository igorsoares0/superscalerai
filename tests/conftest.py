import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


@pytest.fixture(autouse=True)
def local_storage(monkeypatch):
    """Tests never touch R2, even when the developer's .env has credentials."""
    from app.core.config import settings
    from app.services import storage

    monkeypatch.setattr(settings, "r2_bucket", "")
    storage.get_storage.cache_clear()
    yield
    storage.get_storage.cache_clear()


@pytest.fixture(autouse=True)
def sent_emails(monkeypatch) -> list[dict]:
    """Tests never send mail, even when the developer's .env has a Resend key
    — registering now mails on every signup, so without this a test run is a
    hundred real API calls and a hundred real messages.

    Yields the outbox: [{"to", "subject", "html", "text"}, ...]."""
    from app.services import email

    outbox: list[dict] = []

    def capture(to: str, subject: str, html: str, text: str) -> None:
        outbox.append({"to": to, "subject": subject, "html": html, "text": text})

    monkeypatch.setattr(email, "send_email", capture)
    return outbox


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """Each test starts with clean rate-limit counters (they'd otherwise leak
    across tests: every test client shares the same fake IP)."""
    from app.services.ratelimit import limiter

    limiter.reset()
    yield


@pytest.fixture
def anon_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    """Client logged in as a freshly registered user with a CONFIRMED address
    (email on `.user_email`), i.e. one who already has the signup bonus.

    Confirmation is applied straight through the service rather than by
    replaying the emailed link: the raw token only ever exists inside that
    email, by design. The token round-trip has its own tests in
    test_email_verification.py."""
    c = TestClient(app)
    email = f"{uuid.uuid4().hex}@example.com"
    r = c.post("/auth/register", json={"email": email, "password": "password-123"})
    assert r.status_code == 201, r.text
    c.user_email = email
    c.user_id = r.json()["id"]
    verify_user(c.user_id)
    return c


@pytest.fixture
def unverified_client() -> TestClient:
    """Same, but stopped right after signup: no confirmation, no credits."""
    c = TestClient(app)
    email = f"{uuid.uuid4().hex}@example.com"
    r = c.post("/auth/register", json={"email": email, "password": "password-123"})
    assert r.status_code == 201, r.text
    c.user_email = email
    c.user_id = r.json()["id"]
    return c


def verify_user(user_id: str) -> None:
    """Confirm an address and pay out the signup bonus, as /auth/verify does."""
    from app.auth import service
    from app.database.models import User
    from app.database.session import SessionLocal

    with SessionLocal() as db:
        service.grant_signup_bonus(db, db.get(User, user_id))
        db.commit()


def png_bytes(size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "salmon").save(buf, format="PNG")
    return buf.getvalue()
