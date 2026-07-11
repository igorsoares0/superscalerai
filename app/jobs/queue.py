"""Job dispatch.

MVP: in-process FastAPI BackgroundTasks — zero infrastructure. The contract
(run_enhancement(job_id) + jobs.status in the DB) is queue-agnostic, so when
we need multiple workers / retries / scale, this function swaps its body for
an RQ/Redis enqueue and nothing else changes.
"""

from fastapi import BackgroundTasks

from app.workers.enhance import run_enhancement


def enqueue_enhancement(job_id: str, background_tasks: BackgroundTasks) -> None:
    background_tasks.add_task(run_enhancement, job_id)
