"""An upload that can never become a job is storage we pay for and nobody
uses. Both ways of getting there are refused at /images/upload."""

from app.core.config import settings
from app.database.models import ImageRecord, User
from app.database.session import SessionLocal
from tests.conftest import png_bytes


def set_credits(user_id: str, balance: int) -> None:
    with SessionLocal() as db:
        db.get(User, user_id).credits = balance
        db.commit()


def stored_images(user_id: str) -> int:
    with SessionLocal() as db:
        return len(db.query(ImageRecord).filter(ImageRecord.user_id == user_id).all())


def test_unconfirmed_address_cannot_upload(unverified_client):
    r = unverified_client.post(
        "/images/upload", files={"file": ("t.png", png_bytes(), "image/png")}
    )
    assert r.status_code == 403
    assert "confirm your email" in r.json()["detail"]
    assert stored_images(unverified_client.user_id) == 0


def test_empty_balance_cannot_upload(client):
    set_credits(client.user_id, 0)
    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    assert r.status_code == 402
    assert stored_images(client.user_id) == 0


def test_balance_too_small_for_this_image_cannot_upload(client):
    # 3072px in -> 6144px out -> the 8-credit tier; 4 is real money, just not
    # enough money, which is the case the plain "> 0" check would let through
    set_credits(client.user_id, 4)
    big = png_bytes(size=(settings.max_image_px, 10))
    r = client.post("/images/upload", files={"file": ("t.png", big, "image/png")})
    assert r.status_code == 402
    assert "costs 8 credits" in r.json()["detail"]
    assert stored_images(client.user_id) == 0


def test_the_same_small_balance_still_uploads_what_it_can_afford(client):
    set_credits(client.user_id, 4)
    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    assert r.status_code == 201, r.text
    assert stored_images(client.user_id) == 1


def test_exactly_enough_credits_is_enough(client):
    set_credits(client.user_id, 8)
    big = png_bytes(size=(settings.max_image_px, 10))
    r = client.post("/images/upload", files={"file": ("t.png", big, "image/png")})
    assert r.status_code == 201, r.text


def test_confirming_the_address_unblocks_uploading(unverified_client):
    from tests.conftest import verify_user

    blocked = unverified_client.post(
        "/images/upload", files={"file": ("t.png", png_bytes(), "image/png")}
    )
    assert blocked.status_code == 403

    verify_user(unverified_client.user_id)
    r = unverified_client.post(
        "/images/upload", files={"file": ("t.png", png_bytes(), "image/png")}
    )
    assert r.status_code == 201, r.text
