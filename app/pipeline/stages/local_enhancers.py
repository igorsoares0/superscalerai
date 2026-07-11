"""Stage 6: Local Enhancers — corrective stages (SPEC.md).

Both strategies validated on 2026-07-10:

- protect_regions (text/logos): composite back from a deterministic
  upscale of the original, feathered mask. Provider generation-time masks
  are NOT used (Clarity's `mask` disables upscaling).
- face_regions (small faces): zoom-and-enhance — run the generative
  upscaler on the face crop alone, composite back supersampled.
"""

import io

from PIL import Image, ImageDraw, ImageFilter

from app.pipeline.base import PipelineStage, PipelineState
from app.pipeline.context import Box
from app.providers.base import AIProvider


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
            image = self._composite_protected(image, original, box, sx, sy)

        for box in plan.face_regions:
            image = await self._zoom_and_enhance(image, original, box, sx, sy, plan.seed)
        return image

    def _composite_protected(
        self, image: Image.Image, original: Image.Image, box: Box, sx: float, sy: float
    ) -> Image.Image:
        # TODO: use Real-ESRGAN instead of Lanczos for the protected patch
        target = (int(box[0] * sx), int(box[1] * sy), int(box[2] * sx), int(box[3] * sy))
        size = (target[2] - target[0], target[3] - target[1])
        patch = original.crop(box).resize(size, Image.LANCZOS)
        image.paste(patch, target[:2], feathered_mask(size))
        return image

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
                "creativity": 0.25,
                "resemblance": 0.9,
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
