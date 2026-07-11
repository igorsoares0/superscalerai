import io

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app

client = TestClient(app)


def _png_bytes(size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "salmon").save(buf, format="PNG")
    return buf.getvalue()


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_and_list():
    r = client.post("/images/upload", files={"file": ("t.png", _png_bytes(), "image/png")})
    assert r.status_code == 201, r.text
    image_id = r.json()["id"]

    listed = client.get("/images").json()
    assert any(i["id"] == image_id for i in listed)


def test_upload_rejects_non_image():
    r = client.post("/images/upload", files={"file": ("t.txt", b"not an image", "text/plain")})
    assert r.status_code == 415


def test_job_requires_known_preset():
    r = client.post("/jobs", json={"image_id": "whatever", "preset": "nope"})
    assert r.status_code == 422
