import pytest

from app.api import body_limit
from app.core.config import settings
from tests.conftest import png_bytes


@pytest.fixture
def small_cap(monkeypatch):
    """1 MB files (so the whole request caps at ~1.06 MB) — same code path as
    the 25 MB default, without moving 25 MB through the test."""
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    return body_limit.max_body_bytes()


def test_oversized_request_is_rejected(client, small_cap):
    r = client.post(
        "/images/upload",
        files={"file": ("big.png", b"x" * (small_cap + 1), "image/png")},
    )
    assert r.status_code == 413
    assert r.json()["detail"] == "request body too large"


def test_cap_applies_to_every_route_not_just_uploads(anon_client, small_cap):
    """The limit lives in middleware, ahead of routing and body parsing — the
    login endpoint gets it without knowing about it."""
    r = anon_client.post(
        "/auth/login",
        json={"email": "a@example.com", "password": "x" * (small_cap + 1)},
    )
    assert r.status_code == 413


def test_file_over_the_upload_limit_is_rejected_by_the_endpoint(client, small_cap):
    """Between the file limit and the request cap: the endpoint's own check is
    what answers, with the documented limit in the message."""
    over = b"x" * (settings.max_upload_mb * 1024 * 1024 + 1024)
    assert len(over) < small_cap
    r = client.post("/images/upload", files={"file": ("big.png", over, "image/png")})
    assert r.status_code == 413
    assert r.json()["detail"] == "file exceeds 1MB"


def test_normal_upload_is_unaffected(client, small_cap):
    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    assert r.status_code == 201


def test_undeclared_length_is_counted(anon_client, small_cap):
    """A client that streams (chunked: no Content-Length to trust) doesn't get
    a free pass — the bytes are counted as they arrive."""

    def chunks():
        for _ in range(4):
            yield b"x" * (small_cap // 3)

    r = anon_client.post(
        "/auth/login", content=chunks(), headers={"content-type": "application/json"}
    )
    assert r.status_code == 413
