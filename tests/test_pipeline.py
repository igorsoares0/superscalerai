"""Pipeline engine test with a fake provider — no network, no GPU."""

from typing import Any

import pytest
from PIL import Image

from app.pipeline.engine import PipelineEngine
from app.pipeline.stages import Analyzer, Captioner, Planner, PostProcessor, Preprocessor
from app.providers.base import AIProvider


class FakeProvider(AIProvider):
    async def run(self, model: str, input: dict[str, Any]) -> Any:
        if model == "captioner":
            return {"output": "a test image", "metrics": {"predict_time": 0.1}}
        raise NotImplementedError(model)

    async def upload(self, data: bytes, filename: str) -> str:
        return "data:image/png;base64,fake"


@pytest.mark.asyncio
async def test_pipeline_plans_from_caption_and_preset():
    engine = PipelineEngine(
        [Analyzer(), Captioner(FakeProvider()), Planner("portrait", seed=42), Preprocessor(), PostProcessor()]
    )
    state = await engine.run(Image.new("RGB", (100, 80), "salmon"))

    assert state.context is not None and state.context.caption == "a test image"
    plan = state.plan
    assert plan is not None
    assert plan.seed == 42
    assert plan.denoise == 0.28  # portrait preset
    assert "a test image" in plan.prompt
    assert "skin pores" in plan.prompt  # portrait skin terms (validated 2026-07-16)
    assert "plastic skin" in plan.negative_prompt
    assert state.color_reference is not None
    assert set(state.stage_timings) == {"analyzer", "captioner", "planner", "preprocessor", "post_processor"}
