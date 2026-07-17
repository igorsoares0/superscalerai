"""Stage 5: Generative Upscaler — the most important stage (SPEC.md).

Clarity handles tiling and progressive scaling internally, so the MVP
delegates both to the model and runs a single call per job. The
progressive-pass loop becomes ours when we self-host.
"""

import io

from PIL import Image

from app.pipeline.base import PipelineStage, PipelineState
from app.providers.base import AIProvider
from app.providers.replicate import ReplicateProvider


class GenerativeUpscaler(PipelineStage):
    name = "generative_upscaler"

    def __init__(self, provider: AIProvider):
        self.provider = provider

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        plan = state.plan
        assert plan is not None
        input_url = state.artifacts.get("input_url")
        if input_url is None:
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG", quality=95)
            input_url = await self.provider.upload(buf.getvalue(), "input.jpg")
        pred = await self.provider.run(
            "generative-upscaler",
            {
                "image": input_url,
                "prompt": plan.prompt,
                "negative_prompt": plan.negative_prompt,
                "creativity": plan.denoise,
                "resemblance": plan.guidance,
                "dynamic": plan.hdr,
                "scale_factor": plan.scale_factor,
                "seed": plan.seed,
                "num_inference_steps": 18,
            },
        )
        assert isinstance(self.provider, ReplicateProvider)
        data = await self.provider.download(pred["output"][0])
        state.artifacts["upscale_predict_time"] = pred["metrics"]["predict_time"]
        return Image.open(io.BytesIO(data)).convert("RGB")
