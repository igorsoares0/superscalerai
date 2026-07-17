"""The worker semaphore caps how many jobs run at once (Replicate 429 guard)."""

import threading
import time

from app.core.config import settings
from app.workers import enhance


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

    monkeypatch.setattr(enhance, "_run", fake_run)
    threads = [
        threading.Thread(target=enhance.run_enhancement, args=(str(i),)) for i in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak <= settings.max_concurrent_jobs
    assert peak >= 2  # they did overlap — the cap limits, it doesn't serialize
