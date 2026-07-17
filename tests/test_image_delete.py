from pathlib import Path

from app.database.models import CreditLedger, ImageRecord, Job
from app.database.session import SessionLocal
from tests.conftest import png_bytes


def upload(client) -> str:
    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    assert r.status_code == 201
    return r.json()["id"]


def add_job(image_id: str, user_id: str, status: str, with_ledger: bool = False) -> str:
    with SessionLocal() as db:
        job = Job(user_id=user_id, image_id=image_id, preset="portrait", status=status)
        db.add(job)
        db.flush()
        if with_ledger:
            db.add(CreditLedger(user_id=user_id, delta=-1, reason="job_debit", job_id=job.id))
        db.commit()
        return job.id


def test_delete_requires_auth(anon_client):
    assert anon_client.delete("/images/whatever").status_code == 401


def test_delete_unknown_image(client):
    assert client.delete("/images/nope").status_code == 404


def test_delete_someone_elses_image(client, anon_client):
    image_id = upload(client)
    import uuid

    other = anon_client
    other.post(
        "/auth/register",
        json={"email": f"{uuid.uuid4().hex}@example.com", "password": "password-123"},
    )
    assert other.delete(f"/images/{image_id}").status_code == 404
    assert client.get(f"/images/{image_id}").status_code == 200  # untouched


def test_delete_removes_record_and_file(client):
    image_id = upload(client)
    with SessionLocal() as db:
        # rows store storage KEYS, resolved against storage_dir by LocalStorage
        from app.core.config import settings

        original = Path(settings.storage_dir) / db.get(ImageRecord, image_id).original_path
    assert original.exists()

    assert client.delete(f"/images/{image_id}").status_code == 200
    assert client.get(f"/images/{image_id}").status_code == 404
    assert not original.exists()
    assert image_id not in [i["id"] for i in client.get("/images").json()]


def test_delete_keeps_ledger_but_not_jobs(client):
    user_id = client.get("/auth/me").json()["id"]
    image_id = upload(client)
    job_id = add_job(image_id, user_id, status="completed", with_ledger=True)

    assert client.delete(f"/images/{image_id}").status_code == 200

    with SessionLocal() as db:
        assert db.get(Job, job_id) is None
        entry = db.query(CreditLedger).filter_by(user_id=user_id, reason="job_debit").one()
        assert entry.job_id is None  # reference orphaned, history preserved
        assert entry.delta == -1


def test_delete_blocked_while_job_runs(client):
    user_id = client.get("/auth/me").json()["id"]
    image_id = upload(client)
    add_job(image_id, user_id, status="running")

    assert client.delete(f"/images/{image_id}").status_code == 409
    assert client.get(f"/images/{image_id}").status_code == 200  # still there
