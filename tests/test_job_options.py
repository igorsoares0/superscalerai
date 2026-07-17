"""Advanced job options: API validation, persistence, Planner overrides."""

import pytest
from PIL import Image

from app.database.models import Job
from app.database.session import SessionLocal
from app.pipeline.base import PipelineState
from app.pipeline.context import ImageContext
from app.pipeline.stages.planner import Planner
from tests.conftest import png_bytes


@pytest.fixture(autouse=True)
def no_worker(monkeypatch):
    import app.api.jobs as jobs_api

    monkeypatch.setattr(jobs_api, "enqueue_enhancement", lambda job_id, bg: None)


def upload(client) -> str:
    r = client.post("/images/upload", files={"file": ("t.png", png_bytes(), "image/png")})
    return r.json()["id"]


def test_options_persist_on_job(client):
    image_id = upload(client)
    r = client.post("/jobs", json={
        "image_id": image_id, "preset": "portrait",
        "creativity": 0.45, "hdr": 8, "prompt_extra": "  golden hour  ",
    })
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        job = db.get(Job, r.json()["id"])
        assert job.options == {"creativity": 0.45, "hdr": 8, "prompt_extra": "golden hour"}


def test_no_overrides_means_no_options(client):
    image_id = upload(client)
    r = client.post("/jobs", json={"image_id": image_id, "preset": "portrait"})
    assert r.status_code == 201
    with SessionLocal() as db:
        assert db.get(Job, r.json()["id"]).options is None


@pytest.mark.parametrize("field,value", [
    ("creativity", 0.9), ("creativity", 0.01),
    ("resemblance", 2.5), ("hdr", 50), ("prompt_extra", "x" * 200),
])
def test_out_of_range_options_rejected(client, field, value):
    image_id = upload(client)
    r = client.post("/jobs", json={"image_id": image_id, "preset": "portrait", field: value})
    assert r.status_code == 422


def make_state(caption: str = "a red car") -> PipelineState:
    state = PipelineState(original=Image.new("RGB", (100, 100)))
    state.context = ImageContext(width=100, height=100, caption=caption)
    return state


async def test_planner_applies_overrides():
    planner = Planner("portrait", options={
        "creativity": 0.5, "resemblance": 1.2, "hdr": 9,
        "prompt_extra": "golden\n  hour,  film grain ",
    })
    state = make_state()
    await planner.process(state.original, state)
    plan = state.plan
    assert plan.denoise == 0.5
    assert plan.guidance == 1.2
    assert plan.hdr == 9
    assert "a red car, golden hour, film grain" in plan.prompt


async def test_planner_defaults_without_options():
    state = make_state()
    await Planner("portrait").process(state.original, state)
    plan = state.plan
    assert plan.denoise == 0.28  # portrait preset
    assert plan.guidance == 0.8
    assert plan.hdr == 6.0  # Clarity's own default
    assert "a red car" in plan.prompt


async def test_non_portrait_presets_keep_base_prompts():
    from app.pipeline.presets import BASE_NEGATIVE

    state = make_state()
    await Planner("product").process(state.original, state)
    assert "skin" not in state.plan.prompt
    assert state.plan.negative_prompt == BASE_NEGATIVE
