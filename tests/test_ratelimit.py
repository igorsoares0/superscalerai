"""Rate limiting: sliding-window mechanics and per-endpoint enforcement."""

import uuid

from app.core.config import settings
from app.services.ratelimit import RateLimiter

from .conftest import png_bytes


def _creds() -> dict:
    return {"email": f"{uuid.uuid4().hex}@example.com", "password": "password-123"}


# --- limiter mechanics (fake clock) ---


def test_sliding_window_frees_slots_as_hits_expire():
    now = [0.0]
    rl = RateLimiter(clock=lambda: now[0])
    assert rl.check("k", 2, 10) is None
    now[0] = 4.0
    assert rl.check("k", 2, 10) is None
    retry = rl.check("k", 2, 10)
    assert retry == 6.0  # oldest hit (t=0) leaves the window at t=10, 6s from now (t=4)
    now[0] = 10.5  # first hit expired, second (t=4) still counts
    assert rl.check("k", 2, 10) is None
    assert rl.check("k", 2, 10) is not None


def test_blocked_hits_do_not_extend_the_block():
    now = [0.0]
    rl = RateLimiter(clock=lambda: now[0])
    rl.check("k", 1, 10)
    for t in (5.0, 9.0):  # hammering while blocked must not push the reset out
        now[0] = t
        assert rl.check("k", 1, 10) is not None
    now[0] = 10.5
    assert rl.check("k", 1, 10) is None


def test_clear_and_reset_forget_history():
    rl = RateLimiter(clock=lambda: 0.0)
    rl.check("a", 1, 10)
    rl.check("b", 1, 10)
    rl.clear("a")
    assert rl.check("a", 1, 10) is None
    rl.reset()
    assert rl.check("b", 1, 10) is None


def test_prune_drops_stale_keys():
    now = [0.0]
    rl = RateLimiter(clock=lambda: now[0])
    rl.check("stale", 5, 10)
    now[0] = RateLimiter._PRUNE_EVERY + 1  # stale's hit is long outside its window
    rl.check("live", 5, 10)  # triggers the sweep
    assert "stale" not in rl._buckets
    assert "live" in rl._buckets


# --- endpoint enforcement ---


def test_login_429_after_limit(anon_client):
    creds = _creds()
    anon_client.post("/auth/register", json=creds)
    bad = {"email": creds["email"], "password": "wrong-pass-1"}
    # registering consumed nothing on the login keys; the login limit is fresh
    for _ in range(settings.login_rate_limit):
        assert anon_client.post("/auth/login", json=bad).status_code == 401
    r = anon_client.post("/auth/login", json=bad)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1


def test_successful_login_resets_the_email_counter(anon_client, monkeypatch):
    # vary the IP via X-Forwarded-For so only the per-email key is exercised
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    creds = _creds()
    anon_client.post("/auth/register", json=creds)
    bad = {"email": creds["email"], "password": "wrong-pass-1"}

    def login(body, ip):
        return anon_client.post("/auth/login", json=body, headers={"X-Forwarded-For": ip})

    for n in range(settings.login_rate_limit - 1):
        assert login(bad, f"10.0.0.{n}").status_code == 401
    assert login(creds, "10.0.1.1").status_code == 200  # last slot, correct password
    # without the reset the email key would now be exhausted and this would 429
    assert login(bad, "10.0.2.1").status_code == 401


def test_register_429_per_ip(anon_client):
    for _ in range(settings.register_rate_limit):
        assert anon_client.post("/auth/register", json=_creds()).status_code == 201
    r = anon_client.post("/auth/register", json=_creds())
    assert r.status_code == 429


def test_forgot_429_per_ip(anon_client):
    for _ in range(settings.forgot_rate_limit):
        r = anon_client.post("/auth/forgot", json={"email": f"{uuid.uuid4().hex}@example.com"})
        assert r.status_code == 200
    r = anon_client.post("/auth/forgot", json={"email": "another@example.com"})
    assert r.status_code == 429


def test_upload_429_per_user(client, monkeypatch):
    monkeypatch.setattr(settings, "upload_rate_limit", 2)
    for _ in range(2):
        r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
        assert r.status_code == 201
    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    assert r.status_code == 429


def test_forged_forwarded_for_is_ignored_by_default(anon_client):
    # trust_proxy_headers is False: rotating the header must not dodge the limit
    for n in range(settings.register_rate_limit):
        r = anon_client.post(
            "/auth/register", json=_creds(), headers={"X-Forwarded-For": f"172.16.0.{n}"}
        )
        assert r.status_code == 201
    r = anon_client.post(
        "/auth/register", json=_creds(), headers={"X-Forwarded-For": "172.16.0.99"}
    )
    assert r.status_code == 429


def test_rate_limiting_can_be_disabled(anon_client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    for _ in range(settings.register_rate_limit + 2):
        assert anon_client.post("/auth/register", json=_creds()).status_code == 201
