"""In-memory sliding-window rate limiter.

Single-instance by design, like the in-process job runner: counters live in
this process and reset on restart. If the app ever runs on more than one
instance, this moves to a shared store (Redis) — until then a shared store
would be pure overhead.
"""

import threading
import time
from collections import deque


class RateLimiter:
    _PRUNE_EVERY = 600.0  # seconds between sweeps of stale keys

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        # key -> (window, hit timestamps oldest-first)
        self._buckets: dict[str, tuple[float, deque[float]]] = {}
        self._next_prune = clock() + self._PRUNE_EVERY

    def check(self, key: str, limit: int, window: float) -> float | None:
        """Record a hit. None when allowed; otherwise seconds until a slot frees
        (the hit is not recorded, so being limited never extends the block)."""
        now = self._clock()
        with self._lock:
            if now >= self._next_prune:
                self._prune(now)
            _, hits = self._buckets.get(key, (window, deque()))
            self._buckets[key] = (window, hits)
            cutoff = now - window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return hits[0] - cutoff
            hits.append(now)
            return None

    def clear(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def _prune(self, now: float) -> None:
        """Drop keys whose every hit already left its window, so one-off
        clients (or an attacker rotating IPs) can't grow the dict forever."""
        stale = [
            key
            for key, (window, hits) in self._buckets.items()
            if not hits or hits[-1] <= now - window
        ]
        for key in stale:
            del self._buckets[key]
        self._next_prune = now + self._PRUNE_EVERY


limiter = RateLimiter()
