"""Rate-limit enforcement for the HTTP layer."""

import math

from fastapi import HTTPException, Request

from app.core.config import settings
from app.services.ratelimit import limiter


def client_ip(request: Request) -> str:
    """Trust X-Forwarded-For only when a proxy we control sets it; otherwise
    any client could forge the header and dodge every per-IP limit."""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(key: str, limit: int, window_minutes: float) -> None:
    if not settings.rate_limit_enabled:
        return
    retry_in = limiter.check(key, limit, window_minutes * 60)
    if retry_in is not None:
        # generic message: don't advertise the exact limit to attackers
        raise HTTPException(
            429,
            "too many requests, try again later",
            headers={"Retry-After": str(math.ceil(retry_in))},
        )
