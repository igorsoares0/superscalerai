import uuid

from fastapi.testclient import TestClient

from app.main import app


def _creds():
    return {"email": f"{uuid.uuid4().hex}@example.com", "password": "password-123"}


def test_register_login_logout_flow():
    client = TestClient(app)
    creds = _creds()

    r = client.post("/auth/register", json=creds)
    assert r.status_code == 201
    assert r.json()["credits"] == 3  # signup bonus
    assert "session" in client.cookies

    assert client.get("/auth/me").json()["email"] == creds["email"]

    r = client.post("/auth/logout")
    assert r.status_code == 200
    assert client.get("/auth/me").status_code == 401

    r = client.post("/auth/login", json=creds)
    assert r.status_code == 200
    assert client.get("/auth/me").status_code == 200


def test_duplicate_email_rejected():
    client = TestClient(app)
    creds = _creds()
    assert client.post("/auth/register", json=creds).status_code == 201
    assert client.post("/auth/register", json=creds).status_code == 409


def test_wrong_password_and_unknown_email_same_error():
    client = TestClient(app)
    creds = _creds()
    client.post("/auth/register", json=creds)
    client.post("/auth/logout")

    wrong = client.post("/auth/login", json={"email": creds["email"], "password": "wrong-pass-1"})
    unknown = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong-pass-1"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_short_password_rejected():
    client = TestClient(app)
    r = client.post("/auth/register", json={"email": "x@example.com", "password": "short"})
    assert r.status_code == 422


def test_protected_routes_require_auth():
    client = TestClient(app)
    assert client.get("/images").status_code == 401
    assert client.get("/jobs").status_code == 401
    assert client.get("/credits").status_code == 401
    assert client.post("/jobs", json={"image_id": "x", "preset": "portrait"}).status_code == 401
