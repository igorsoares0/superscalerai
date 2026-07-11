"""Stage 2: Captioner — generates the Internal Prompt (SPEC.md)."""

import io

from PIL import Image

from app.pipeline.base import PipelineStage, PipelineState
from app.providers.base import AIProvider


class Captioner(PipelineStage):
    name = "captioner"

    def __init__(self, provider: AIProvider):
        self.provider = provider

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=90)
        url = await self.provider.upload(buf.getvalue(), "input.jpg")
        state.artifacts["input_url"] = url
        pred = await self.provider.run("captioner", {"image": url, "caption": True})
        assert state.context is not None
        state.context.caption = pred["output"]
        return image
