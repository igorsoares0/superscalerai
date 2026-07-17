"""Stage 2: Captioner — generates the Internal Prompt (SPEC.md).

Florence-2 (MIT) replaced BLIP-2 on 2026-07-16: BLIP-2 got brand/gender
wrong on the validation photos ("nike men's collection" for a woman in
New Balance), and the wrong caption steered the generative pass into
masculinizing the subject. "Detailed Caption" is the level validated in
the pixel A/B — "More Detailed" overflows SD 1.5's prompt encoder.
"""

import ast
import io
import logging

from PIL import Image

from app.pipeline.base import PipelineStage, PipelineState
from app.providers.base import AIProvider

logger = logging.getLogger(__name__)

TASK = "Detailed Caption"


class Captioner(PipelineStage):
    name = "captioner"

    def __init__(self, provider: AIProvider):
        self.provider = provider

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=90)
        url = await self.provider.upload(buf.getvalue(), "input.jpg")
        state.artifacts["input_url"] = url
        pred = await self.provider.run("captioner", {"image": url, "task_input": TASK})
        assert state.context is not None
        state.context.caption = parse_caption(pred["output"])
        return image


def parse_caption(output: object) -> str | None:
    """Florence-2 wraps the caption as {'img': ..., 'text': "{'<TASK>': '...'}"}.

    A missing caption is survivable (the Planner falls back to the preset
    name), so parse failures log and return None instead of failing the job.
    """
    try:
        parsed = ast.literal_eval(output["text"])  # type: ignore[index]
        caption = str(next(iter(parsed.values()))).strip()
        return caption or None
    except Exception:  # noqa: BLE001 — any shape surprise ends up here
        logger.warning("unparseable captioner output: %r", output)
        return None
