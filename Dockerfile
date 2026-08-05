# Build and runtime share one base image so the virtualenv copied between
# stages keeps pointing at an interpreter that actually exists.
FROM python:3.13-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

FROM base AS build
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv

# Dependencies resolve from the lock alone, so this layer survives every code
# change. It is the expensive one: opencv + numpy + boto3 are ~400 MB.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM base AS runtime
# Nothing here builds or writes to the image: no compiler, no uv, no root.
# opencv-python-headless bundles its own libs (no libGL, no libgomp needed).
RUN useradd --system --create-home --uid 10001 app
WORKDIR /srv
COPY --from=build --chown=app:app /srv /srv
# storage/ is only used when R2 is unconfigured, but the pipeline expects the
# directory to exist and a non-root process can't create it under /srv.
RUN mkdir -p /srv/storage && chown app:app /srv/storage
ENV PATH="/srv/.venv/bin:$PATH"
USER app
EXPOSE 8000

# /health is the cheapest route in the app: no DB, no storage.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# ONE worker, deliberately: run_migrations() executes at import time
# (app/main.py:22) and N workers would race on the same Alembic upgrade.
# Jobs also run in-process, so the worker count is the concurrency ceiling.
# No --proxy-headers: client IPs are resolved by app/api/ratelimit.py from
# TRUST_PROXY_HEADERS, and having both rewrite the same header hides which
# one is in charge.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
