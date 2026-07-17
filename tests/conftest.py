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


@pytest.fixture
def anon_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    """Client logged in as a freshly registered user (email on `.user_email`)."""
    c = TestClient(app)
    email = f"{uuid.uuid4().hex}@example.com"
    r = c.post("/auth/register", json={"email": email, "password": "password-123"})
    assert r.status_code == 201, r.text
    c.user_email = email
    return c


def png_bytes(size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "salmon").save(buf, format="PNG")
    return buf.getvalue()
