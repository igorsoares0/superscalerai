"""Stage 2: Captioner — generates the Internal Prompt (SPEC.md).

Florence-2 (MIT) replaced BLIP-2 on 2026-07-16: BLIP-2 got brand/gender
wrong on the validation photos ("nike men's collection" for a woman in
New Balance), and the wrong caption steered the generative pass into
masculinizing the subject. "Detailed Caption" is the level validated in
the pixel A/B — "More Detailed" overflows SD 1.5's prompt encoder.

Since 2026-07-21 this stage also runs Florence's "OCR with Region" task
(same model, second prediction, concurrent with the caption) when the
preset protects text: its boxes replace the Analyzer's gradient
heuristic in context.text_regions — the OCR read "New Balance" exactly
where the heuristic guessed. OCR failure keeps the heuristic boxes; a
missing caption is survivable, so both parse helpers return None
instead of raising.
"""

import ast
import asyncio
import io
import logging

from PIL import Image

from app.pipeline import analysis
from app.pipeline.base import PipelineStage, PipelineState
from app.pipeline.context import Box
from app.providers.base import AIProvider

logger = logging.getLogger(__name__)

TASK = "Detailed Caption"
OCR_TASK = "OCR with Region"


class Captioner(PipelineStage):
    name = "captioner"

    def __init__(self, provider: AIProvider, ocr: bool = False):
        self.provider = provider
        self.ocr = ocr

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=90)
        url = await self.provider.upload(buf.getvalue(), "input.jpg")
        state.artifacts["input_url"] = url
        assert state.context is not None

        caption_call = self.provider.run("captioner", {"image": url, "task_input": TASK})
        if not self.ocr:
            pred = await caption_call
        else:
            ocr_call = self.provider.run("captioner", {"image": url, "task_input": OCR_TASK})
            pred, ocr_pred = await asyncio.gather(caption_call, ocr_call, return_exceptions=True)
            if isinstance(pred, BaseException):
                raise pred  # no caption prediction at all fails the job, as before
            if isinstance(ocr_pred, BaseException):
                logger.warning("OCR prediction failed; keeping heuristic text regions: %r", ocr_pred)
            else:
                regions = parse_ocr_regions(ocr_pred["output"], image.width, image.height)
                if regions is not None:
                    state.context.text_regions = regions

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


def parse_ocr_regions(output: object, width: int, height: int) -> list[Box] | None:
    """OCR task wraps regions as {'text': "{'<OCR_WITH_REGION>':
    {'quad_boxes': [[x1,y1,...,x4,y4], ...], 'labels': ['</s>...', ...]}}"}.

    None = unparseable (caller keeps the heuristic boxes); an empty list
    is a valid answer (no text — drops the heuristic's false positives).
    """
    try:
        parsed = ast.literal_eval(output["text"])  # type: ignore[index]
        regions = next(iter(parsed.values()))
        pairs = list(zip(regions["quad_boxes"], regions["labels"], strict=True))
        return analysis.ocr_text_regions(pairs, width, height)
    except Exception:  # noqa: BLE001 — any shape surprise ends up here
        logger.warning("unparseable OCR output: %r", output)
        return None
