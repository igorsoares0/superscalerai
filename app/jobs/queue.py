"""Job dispatch.

Jobs run in a thread pool of their own, deliberately NOT in FastAPI's
BackgroundTasks. BackgroundTasks hands a sync function to Starlette's
threadpool — the same 40-slot pool (anyio's default CapacityLimiter) that
every `def` route in this app already runs in. A job holds its thread for its
whole 30-90s, so 40 jobs in flight left zero threads for HTTP: login,
downloads, the Paddle webhook and even /health stopped answering until the
queue drained. Small images cost 1 credit and nothing rate-limits POST /jobs,
so reaching 40 was cheap.

This pool is separate, so a queue of jobs waits on its own threads and the
request path is never starved. `max_workers` is also where job concurrency is
capped now (Replicate 429s around 8 parallel predictions) — that used to be a
semaphore inside the worker, which is what made queued jobs hold threads while
blocked. `reserve()` bounds how much can pile up behind the workers.

Nothing here survives a restart, and nothing needs to: app/main.py fails and
refunds every job left "queued"/"running" at startup.

The contract (run_enhancement(job_id) + jobs.status in the DB) is still
queue-agnostic, so this becomes an RQ/Redis enqueue and nothing else changes.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from app.core.config import settings
from app.workers.enhance import run_enhancement

logger = logging.getLogger(__name__)


class QueueFull(Exception):
    """The whole queue is at max_queued_jobs. Callers answer 503 — everyone
    is waiting, not just whoever asked."""


class TooManyUserJobs(Exception):
    """This account alone is at max_queued_jobs_per_user. Callers answer 429:
    unlike QueueFull this one really is "you asked too often", and the wait is
    for their own jobs to finish."""


_executor = ThreadPoolExecutor(
    max_workers=settings.max_concurrent_jobs, thread_name_prefix="job"
)
_lock = threading.Lock()
_in_flight = 0  # reserved but not yet finished: running AND waiting
_per_user: dict[str, int] = {}  # same, keyed by owner


def reserve(user_id: str) -> None:
    """Claim a place in the queue, or raise.

    Called BEFORE the job row and the credit debit: a job the queue would
    refuse must not cost anyone credits, and this is the last moment where we
    can still say no without having written anything.

    The per-user cap is checked first. When both are hit, "you already have 3
    running" is the answer that tells someone what to do; "the server is busy"
    would be true but useless.
    """
    global _in_flight
    with _lock:
        mine = _per_user.get(user_id, 0)
        if mine >= settings.max_queued_jobs_per_user:
            raise TooManyUserJobs(f"{mine} jobs already in flight for this user")
        if _in_flight >= settings.max_queued_jobs:
            raise QueueFull(f"{_in_flight} jobs already in flight")
        _in_flight += 1
        _per_user[user_id] = mine + 1


def release(user_id: str) -> None:
    """Give back a reservation that never became a running job."""
    global _in_flight
    with _lock:
        _in_flight = max(0, _in_flight - 1)
        remaining = _per_user.get(user_id, 0) - 1
        if remaining > 0:
            _per_user[user_id] = remaining
        else:
            # dropped rather than left at zero: this dict would otherwise grow
            # one entry per user forever
            _per_user.pop(user_id, None)


def in_flight(user_id: str | None = None) -> int:
    with _lock:
        return _in_flight if user_id is None else _per_user.get(user_id, 0)


def enqueue_enhancement(job_id: str, user_id: str) -> None:
    """Hand a job to the pool. The caller must hold a reserve()d slot."""
    _executor.submit(_run_and_release, job_id, user_id)


def _run_and_release(job_id: str, user_id: str) -> None:
    try:
        run_enhancement(job_id)
    except BaseException:  # noqa: BLE001 — nobody awaits this future
        # run_enhancement records its own failures in the DB, so anything
        # landing here escaped that. Nothing reads the future, so without this
        # the traceback would vanish and the slot would still leak.
        logger.exception("job %s crashed outside the worker's own handler", job_id)
    finally:
        release(user_id)
