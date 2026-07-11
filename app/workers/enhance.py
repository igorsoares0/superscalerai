"""Run the enhancement pipeline for a Job row.

MVP: executed in-process via FastAPI BackgroundTasks (threadpool). The same
function becomes an RQ/Celery task unchanged when we move to real workers.
"""

import asyncio
import logging
import time

from PIL import Image

from app.database.models import ImageRecord, Job
from app.database.session import SessionLocal
from app.pipeline.factory import build_pipeline

logger = logging.getLogger(__name__)


def run_enhancement(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            logger.error("job %s not found", job_id)
            return
        image_row = db.get(ImageRecord, job.image_id)
        assert image_row is not None
        job.status = "running"
        db.commit()

        start = time.monotonic()
        try:
            image = Image.open(image_row.original_path)
            pipeline = build_pipeline(job.id, job.preset, seed=job.seed)
            state = asyncio.run(pipeline.run(image))

            assert state.plan is not None
            job.params = state.plan.model_dump()
            job.seed = state.plan.seed
            job.provider = "replicate"
            job.status = "completed"
            image_row.enhanced_path = state.artifacts["enhanced_path"]
            image_row.thumb_path = state.artifacts["thumb_path"]
        except Exception as exc:  # noqa: BLE001 — job boundary
            logger.exception("job %s failed", job_id)
            job.status = "failed"
            job.error_message = str(exc)
            # TODO: refund credits on failure (SPEC.md: credit ledger)
        finally:
            job.execution_time = time.monotonic() - start
            db.commit()
