# SuperScaler AI

AI image enhancement SaaS — see [SPEC.md](SPEC.md) for the full specification.

## Dev setup

```bash
cp .env.example .env          # fill in REPLICATE_API_TOKEN
uv sync
uv run uvicorn app.main:app --reload   # API on :8000 — that's all
```

Jobs run in-process via BackgroundTasks (no Redis/queue at this stage);
`app/jobs/queue.py` is the single swap point when real workers are needed.

## Vertical slice (no auth yet — runs as a dev user)

```bash
curl -F file=@photo.jpg localhost:8000/images/upload      # -> image id
curl -X POST localhost:8000/jobs -H 'content-type: application/json' \
     -d '{"image_id": "<id>", "preset": "portrait"}'      # -> job id
curl localhost:8000/jobs/<job-id>                         # poll status
curl -O localhost:8000/download/<image-id>                # enhanced result
```

## Tests

```bash
uv run pytest
```

## Validation experiments

`validation/validate.py` runs the pipeline core standalone against Replicate
(no queue/DB). See SPEC.md → Initial Models for the licensing rules.
