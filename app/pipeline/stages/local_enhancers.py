"""Stage 6: Local Enhancers — corrective stages (SPEC.md).

Both strategies validated on 2026-07-10:

- protect_regions (text/logos): composite back from a deterministic
  upscale (Real-ESRGAN) of the original, feathered mask. Provider
  generation-time masks are NOT used (Clarity's `mask` disables
  upscaling). If Real-ESRGAN fails, fall back to Lanczos — a softer
  patch beats failing a job whose generative pass already succeeded.
- face_regions (small faces): zoom-and-enhance — run the generative
  upscaler on the face crop alone, composite back supersampled.
"""

import io
import logging
import math

from PIL import Image, ImageDraw, ImageFilter

from app.pipeline.base import PipelineStage, PipelineState
from app.pipeline.context import Box
from app.providers.base import AIProvider

logger = logging.getLogger(__name__)


def feathered_mask(size: tuple[int, int], pad: int = 20, radius: int = 60, blur: int = 20) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (pad, pad, size[0] - pad, size[1] - pad), radius=radius, fill=255
    )
    return mask.filter(ImageFilter.GaussianBlur(blur))


class LocalEnhancers(PipelineStage):
    """Executes the ExecutionPlan's regions; which faces/regions qualify is
    decided by the Planner, not here."""

    name = "local_enhancers"

    def __init__(self, provider: AIProvider):
        self.provider = provider

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        plan, original = state.plan, state.original
        assert plan is not None
        sx = image.width / original.width
        sy = image.height / original.height

        for box in plan.protect_regions:
            image = await self._composite_protected(image, original, box, sx, sy)

        for box in plan.face_regions:
            image = await self._zoom_and_enhance(image, original, box, sx, sy, plan.seed)
        return image

    async def _composite_protected(
        self, image: Image.Image, original: Image.Image, box: Box, sx: float, sy: float
    ) -> Image.Image:
        target = (int(box[0] * sx), int(box[1] * sy), int(box[2] * sx), int(box[3] * sy))
        size = (target[2] - target[0], target[3] - target[1])
        crop = original.crop(box)
        try:
            patch = await self._deterministic_upscale(crop, max(sx, sy))
        except Exception:
            logger.warning(
                "deterministic upscale failed for region %s; falling back to Lanczos",
                box,
                exc_info=True,
            )
            patch = crop
        image.paste(patch.resize(size, Image.LANCZOS), target[:2], feathered_mask(size))
        return image

    async def _deterministic_upscale(self, crop: Image.Image, scale: float) -> Image.Image:
        buf = io.BytesIO()
        crop.convert("RGB").save(buf, format="PNG")
        url = await self.provider.upload(buf.getvalue(), "protect.png")
        pred = await self.provider.run(
            "deterministic-upscaler",
            {
                "image": url,
                # never below 4: the extra pixels supersample the Lanczos
                # fit back to the exact target, sharpening text edges
                "scale": max(4, math.ceil(scale)),
                "face_enhance": False,  # GFPGAN is license-blocked (SPEC.md)
            },
        )
        data = await self.provider.download(pred["output"])  # type: ignore[attr-defined]
        return Image.open(io.BytesIO(data)).convert("RGB")

    async def _zoom_and_enhance(
        self, image: Image.Image, original: Image.Image, box: Box, sx: float, sy: float, seed: int
    ) -> Image.Image:
        crop = original.crop(box)
        buf = io.BytesIO()
        crop.convert("RGB").save(buf, format="PNG")
        url = await self.provider.upload(buf.getvalue(), "face.png")
        pred = await self.provider.run(
            "generative-upscaler",
            {
                "image": url,
                # calibrated 2026-07-21 (validation/calibrate_faces.py): identity
                # collapses as creativity rises (SFace 0.92 @ 0.10 vs 0.65 @ 0.25,
                # with visible skin-tone drift); 0.10 still out-details the input
                "creativity": 0.10,
                "resemblance": 1.2,
                "scale_factor": 4,
                "seed": seed,
                "num_inference_steps": 18,
            },
        )
        data = await self.provider.download(pred["output"][0])  # type: ignore[attr-defined]
        enhanced = Image.open(io.BytesIO(data)).convert("RGB")

        target = (int(box[0] * sx), int(box[1] * sy), int(box[2] * sx), int(box[3] * sy))
        size = (target[2] - target[0], target[3] - target[1])
        enhanced = enhanced.resize(size, Image.LANCZOS)  # 4x -> target = supersampled
        image.paste(enhanced, target[:2], feathered_mask(size, pad=24, radius=70, blur=24))
        return image
