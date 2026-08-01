import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import billing, credits, download, images, jobs
from app.api.body_limit import BodySizeLimitMiddleware
from app.core.config import config_problems, settings
from app.auth import router as auth
from app.auth import service as auth_service
from app.database.migrate import run_migrations
from app.database.models import Job
from app.database.session import engine
from app.web import router as web
from app.services import credits as credits_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_fatal, _warnings = config_problems(settings)
for _problem in _warnings:
    logger.warning("config: %s", _problem)
if _fatal:  # refuse to serve rather than serve silently wrong
    raise RuntimeError(
        "production config is not safe to serve:\n  - " + "\n  - ".join(_fatal)
    )

app = FastAPI(title="SuperScaler AI")

# Outermost: a body that never gets buffered can't fill the disk or the heap.
app.add_middleware(BodySizeLimitMiddleware)

run_migrations()

# Jobs run in-process (BackgroundTasks): anything still "running"/"queued"
# at startup was interrupted by a restart and will never finish.
with Session(engine) as _db:
    stale = _db.scalars(select(Job).where(Job.status.in_(("queued", "running"))))
    for _job in stale:
        _job.status = "failed"
        _job.error_message = "interrupted by server restart"
        credits_service.refund_job(_db, _job)
    _db.commit()
    auth_service.purge_expired_sessions(_db)

app.include_router(auth.router)
app.include_router(images.router)
app.include_router(jobs.router)
app.include_router(credits.router)
app.include_router(billing.router)
app.include_router(download.router)
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
