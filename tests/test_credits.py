import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.database.models import CreditLedger, ImageRecord, Job, User
from app.database.session import SessionLocal
from app.main import app
from app.services import credits

client = TestClient(app)


def test_job_cost_tiers():
    assert credits.job_cost(512, 512) == 1  # 1024 output
    assert credits.job_cost(1024, 768) == 2  # 2048 output
    assert credits.job_cost(2048, 2048) == 4
    assert credits.job_cost(4000, 3000) == 4  # capped tier


def _make_user_and_job(db, balance: int):
    user = User(email=f"{uuid.uuid4()}@test", password_hash="!", credits=balance)
    db.add(user)
    db.flush()
    image = ImageRecord(user_id=user.id, original_path="x", width=100, height=100)
    db.add(image)
    db.flush()
    job = Job(user_id=user.id, image_id=image.id, preset="portrait", status="queued")
    db.add(job)
    db.flush()
    return user, job


def test_debit_and_idempotent_refund():
    with SessionLocal() as db:
        user, job = _make_user_and_job(db, balance=10)
        credits.debit_for_job(db, user, job, 3)
        db.commit()

        db.refresh(user)
        assert user.credits == 7
        assert job.credits_cost == 3

        assert credits.refund_job(db, job) is True
        db.commit()
        db.refresh(user)
        assert user.credits == 10

        # second refund must be a no-op
        assert credits.refund_job(db, job) is False
        db.refresh(user)
        assert user.credits == 10

        entries = db.query(CreditLedger).filter_by(job_id=job.id).all()
        assert sorted(e.delta for e in entries) == [-3, 3]


def test_debit_insufficient_balance():
    with SessionLocal() as db:
        user, job = _make_user_and_job(db, balance=1)
        db.commit()
        with pytest.raises(credits.InsufficientCredits):
            credits.debit_for_job(db, user, job, 2)
        db.rollback()
        db.refresh(user)
        assert user.credits == 1


def test_job_creation_returns_402_without_credits():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "salmon").save(buf, format="PNG")
    r = client.post("/images/upload", files={"file": ("t.png", buf.getvalue(), "image/png")})
    image_id = r.json()["id"]

    with SessionLocal() as db:
        dev = db.query(User).filter_by(email="dev@localhost").one()
        original = dev.credits
        dev.credits = 0
        db.commit()

    try:
        r = client.post("/jobs", json={"image_id": image_id, "preset": "portrait"})
        assert r.status_code == 402
    finally:
        with SessionLocal() as db:
            db.query(User).filter_by(email="dev@localhost").update({"credits": original})
            db.commit()


def test_credits_endpoint_reports_balance_and_ledger():
    r = client.get("/credits")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["balance"], int)
    assert isinstance(body["ledger"], list)
