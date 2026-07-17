from tests.conftest import png_bytes


def test_health(anon_client):
    assert anon_client.get("/health").json() == {"status": "ok"}


def test_upload_and_list(client):
    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    assert r.status_code == 201, r.text
    image_id = r.json()["id"]

    listed = client.get("/images").json()
    assert any(i["id"] == image_id for i in listed)


def test_upload_rejects_non_image(client):
    r = client.post("/images/upload", files={"file": ("t.txt", b"not an image", "text/plain")})
    assert r.status_code == 415


def test_upload_rejects_oversized_image(client):
    from app.core.config import settings

    big = png_bytes(size=(settings.max_image_px + 1, 10))
    r = client.post("/images/upload", files={"file": ("t.png", big, "image/png")})
    assert r.status_code == 413
    assert str(settings.max_image_px) in r.json()["detail"]


def test_upload_accepts_image_at_the_cap(client):
    from app.core.config import settings

    edge = png_bytes(size=(settings.max_image_px, 10))
    r = client.post("/images/upload", files={"file": ("t.png", edge, "image/png")})
    assert r.status_code == 201, r.text
    assert r.json()["width"] == settings.max_image_px


def test_job_requires_known_preset(client):
    r = client.post("/jobs", json={"image_id": "whatever", "preset": "nope"})
    assert r.status_code == 422


def test_users_cannot_see_each_others_images(client, anon_client):
    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    image_id = r.json()["id"]

    other = anon_client
    other.post(
        "/auth/register",
        json={"email": f"other-{image_id[:8]}@example.com", "password": "password-123"},
    )
    assert other.get(f"/images/{image_id}").status_code == 404
