from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.models import ImageRecord, Job, User
from app.database.session import get_db
from app.jobs.queue import enqueue_enhancement
from app.pipeline.presets import PRESETS
from app.services import credits

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobCreate(BaseModel):
    image_id: str
    preset: str = "portrait"
    seed: int | None = None


@router.post("", status_code=201)
def create_job(
    body: JobCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if body.preset not in PRESETS:
        raise HTTPException(422, f"unknown preset {body.preset!r}")
    image = db.get(ImageRecord, body.image_id)
    if image is None or image.user_id != user.id:
        raise HTTPException(404, "image not found")
    job = Job(user_id=user.id, image_id=image.id, preset=body.preset, seed=body.seed, status="queued")
    db.add(job)
    db.flush()  # assigns job.id for the ledger entry
    cost = credits.job_cost(image.width, image.height)
    try:
        credits.debit_for_job(db, user, job, cost)
    except credits.InsufficientCredits:
        db.rollback()
        raise HTTPException(402, f"insufficient credits: job needs {cost}")
    db.commit()
    enqueue_enhancement(job.id, background_tasks)
    return {"id": job.id, "status": job.status, "credits_cost": cost}


@router.get("/{job_id}")
def get_job(
    job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    job = db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, "job not found")
    return {
        "id": job.id,
        "status": job.status,
        "preset": job.preset,
        "error": job.error_message,
        "execution_time": job.execution_time,
    }


@router.get("")
def list_jobs(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    rows = db.scalars(select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc()))
    return [{"id": j.id, "status": j.status, "preset": j.preset} for j in rows]
