import logging

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import download, images, jobs
from app.auth import router as auth
from app.database.models import Base, Job
from app.database.session import engine

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="SuperScaler AI")

# Dev bootstrap; replaced by Alembic migrations before any real deploy
Base.metadata.create_all(engine)

# Jobs run in-process (BackgroundTasks): anything still "running"/"queued"
# at startup was interrupted by a restart and will never finish.
with Session(engine) as _db:
    stale = _db.scalars(select(Job).where(Job.status.in_(("queued", "running"))))
    for _job in stale:
        _job.status = "failed"
        _job.error_message = "interrupted by server restart"
    _db.commit()

app.include_router(auth.router)
app.include_router(images.router)
app.include_router(jobs.router)
app.include_router(download.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
