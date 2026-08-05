"""The job pool caps how many jobs run at once (Replicate 429 guard) and how
many can pile up behind them — and, above all, keeps both off the threadpool
that serves HTTP requests."""

import threading
import time

import pytest

from app.core.config import settings
from app.jobs import queue
from tests.conftest import png_bytes


@pytest.fixture(autouse=True)
def drained():
    """Every test here leaves the queue empty for the next one."""
    yield
    deadline = time.monotonic() + 5
    while queue.in_flight() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert queue.in_flight() == 0, "a reservation leaked"


def _submit(n: int, user_id: str | None = None) -> None:
    """A distinct owner per job unless one is named — the per-user cap would
    otherwise refuse anything past the third."""
    for i in range(n):
        owner = user_id or f"user-{i}"
        queue.reserve(owner)
        queue.enqueue_enhancement(str(i), owner)


def test_concurrent_jobs_capped(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_run(job_id: str) -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1

    monkeypatch.setattr(queue, "run_enhancement", fake_run)
    _submit(10)

    deadline = time.monotonic() + 5
    while queue.in_flight() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert peak <= settings.max_concurrent_jobs
    assert peak >= 2  # they did overlap — the cap limits, it doesn't serialize


def test_queue_refuses_beyond_the_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_queued_jobs", 3)
    monkeypatch.setattr(settings, "max_queued_jobs_per_user", 99)  # global cap only
    for i in range(3):
        queue.reserve(f"user-{i}")
    with pytest.raises(queue.QueueFull):
        queue.reserve("user-x")

    queue.release("user-0")
    queue.reserve("user-x")  # a freed slot is reusable
    for uid in ("user-1", "user-2", "user-x"):
        queue.release(uid)


def test_one_user_cannot_monopolise_the_queue(monkeypatch):
    """The global ceiling alone is monopolisable: one account with enough
    credits fills it and everyone else gets a 503 caused by one person."""
    monkeypatch.setattr(settings, "max_queued_jobs", 20)
    monkeypatch.setattr(settings, "max_queued_jobs_per_user", 3)

    for _ in range(3):
        queue.reserve("hog")
    with pytest.raises(queue.TooManyUserJobs):
        queue.reserve("hog")

    queue.reserve("somebody-else")  # room is still there for everyone else
    assert queue.in_flight("hog") == 3

    queue.release("hog")
    queue.reserve("hog")  # finishing one buys the next
    for _ in range(3):
        queue.release("hog")
    queue.release("somebody-else")


def test_releasing_forgets_the_user(monkeypatch):
    """_per_user would otherwise keep one entry per account that ever ran a
    job, forever."""
    queue.reserve("transient")
    assert queue.in_flight("transient") == 1
    queue.release("transient")
    assert "transient" not in queue._per_user


def test_a_finished_job_frees_its_slot(monkeypatch):
    monkeypatch.setattr(queue, "run_enhancement", lambda job_id: None)
    _submit(3)
    deadline = time.monotonic() + 5
    while queue.in_flight() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert queue.in_flight() == 0


def test_a_crashing_job_frees_its_slot(monkeypatch):
    """The pool holds the only reference to the future and nobody awaits it,
    so a crash that didn't release would leak a slot silently until the queue
    wedged shut."""
    def boom(job_id: str) -> None:
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(queue, "run_enhancement", boom)
    _submit(2)
    deadline = time.monotonic() + 5
    while queue.in_flight() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert queue.in_flight() == 0


def test_full_queue_costs_no_credits(client, monkeypatch):
    """503 has to be free: the reservation is claimed before the debit
    precisely so a refused job never touches the balance."""
    monkeypatch.setattr(queue, "run_enhancement", lambda job_id: None)
    monkeypatch.setattr(settings, "max_queued_jobs", 0)

    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    image_id = r.json()["id"]
    before = client.get("/credits").json()["balance"]

    r = client.post("/jobs", json={"image_id": image_id, "preset": "portrait"})
    assert r.status_code == 503, r.text
    assert r.headers["Retry-After"] == "60"
    assert client.get("/credits").json()["balance"] == before


def test_a_full_queue_still_serves_requests(anon_client, monkeypatch):
    """The regression test for the reason this pool exists.

    Jobs used to run as FastAPI BackgroundTasks, i.e. on Starlette's
    threadpool — the same 40-slot anyio limiter every `def` route uses. Enough
    jobs in flight and the app stopped answering anything: login, downloads,
    the Paddle webhook, /health. Here 50 jobs are wedged open at once; the
    request path must not notice.
    """
    monkeypatch.setattr(settings, "max_queued_jobs", 60)
    hold = threading.Event()
    # timeout, not a bare wait(): a regression must fail this test, not hang it
    monkeypatch.setattr(queue, "run_enhancement", lambda job_id: hold.wait(timeout=30))

    try:
        _submit(50)  # more than the threadpool's 40 slots
        start = time.monotonic()
        assert anon_client.get("/health").status_code == 200
        assert time.monotonic() - start < 2, "the job queue is starving the request path"
    finally:
        hold.set()


def test_api_refuses_a_users_fourth_concurrent_job(client, monkeypatch):
    """End to end, and it must cost nothing: the reservation is taken before
    the debit precisely so a refused job never touches the balance."""
    hold = threading.Event()
    monkeypatch.setattr(queue, "run_enhancement", lambda job_id: hold.wait(timeout=30))
    monkeypatch.setattr(settings, "max_queued_jobs_per_user", 2)

    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    image_id = r.json()["id"]
    job = {"image_id": image_id, "preset": "portrait"}
    try:
        assert client.post("/jobs", json=job).status_code == 201
        assert client.post("/jobs", json=job).status_code == 201
        before = client.get("/credits").json()["balance"]

        r = client.post("/jobs", json=job)
        assert r.status_code == 429, r.text
        assert r.headers["Retry-After"] == "30"
        assert client.get("/credits").json()["balance"] == before
    finally:
        hold.set()


def test_job_creation_reserves_and_releases(client, monkeypatch):
    """The happy path returns the slot once the job finishes."""
    monkeypatch.setattr(queue, "run_enhancement", lambda job_id: None)

    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    image_id = r.json()["id"]
    r = client.post("/jobs", json={"image_id": image_id, "preset": "portrait"})
    assert r.status_code == 201, r.text

    deadline = time.monotonic() + 5
    while queue.in_flight() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert queue.in_flight() == 0
