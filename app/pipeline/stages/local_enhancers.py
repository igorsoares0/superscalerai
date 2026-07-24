"""Stage 6: Local Enhancers — corrective stages (SPEC.md).

Both strategies validated on 2026-07-10:

- protect_regions (text/logos): composite back from a deterministic
  upscale (Real-ESRGAN) of the original, feathered mask. Provider
  generation-time masks are NOT used (Clarity's `mask` disables
  upscaling). If Real-ESRGAN fails, fall back to Lanczos — a softer
  patch beats failing a job whose generative pass already succeeded.
- face_regions: zoom-and-enhance — run the generative upscaler on the face
  crop alone, composite back supersampled. An identity gate measures SFace
  similarity vs the original crop and retries at lower creativity if it drifts.
"""

import io
import logging
import math

from PIL import Image, ImageDraw, ImageFilter

from app.pipeline import analysis
from app.pipeline.base import PipelineStage, PipelineState
from app.pipeline.context import Box
from app.providers.base import AIProvider

logger = logging.getLogger(__name__)

# identity gate (item 3, 2026-07-24): the face pass at face_creativity is
# validated safe (SFace ~0.92 @ 0.10), but a degraded or unusual face can still
# drift. Below IDENTITY_MIN we retry once at lower creativity — favouring
# fidelity over new detail — and keep the best-scoring result. Mostly a measured
# backstop: the similarity is recorded per face regardless. The threshold wants
# GPU calibration (validation's different-person floor is 0.363).
IDENTITY_MIN = 0.5
IDENTITY_MAX_RETRIES = 1
IDENTITY_RETRY_FACTOR = 0.5


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
            image = await self._zoom_and_enhance(
                image, original, box, sx, sy, plan.seed, plan.face_creativity, state
            )
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

    async def _face_pass(self, crop: Image.Image, seed: int, creativity: float) -> Image.Image:
        buf = io.BytesIO()
        crop.convert("RGB").save(buf, format="PNG")
        url = await self.provider.upload(buf.getvalue(), "face.png")
        pred = await self.provider.run(
            "generative-upscaler",
            {
                "image": url,
                # face creativity is independent of the main (background) pass:
                # calibrated 2026-07-21 (validation/calibrate_faces.py) to 0.10,
                # where identity holds (SFace 0.92 @ 0.10 vs 0.65 @ 0.25, with
                # visible skin-tone drift) while still out-detailing the input
                "creativity": creativity,
                "resemblance": 1.2,
                "scale_factor": 4,
                "seed": seed,
                "num_inference_steps": 18,
            },
        )
        data = await self.provider.download(pred["output"][0])  # type: ignore[attr-defined]
        return Image.open(io.BytesIO(data)).convert("RGB")

    async def _zoom_and_enhance(
        self,
        image: Image.Image,
        original: Image.Image,
        box: Box,
        sx: float,
        sy: float,
        seed: int,
        creativity: float,
        state: PipelineState,
    ) -> Image.Image:
        crop = original.crop(box)
        enhanced = await self._face_pass(crop, seed, creativity)

        # identity gate: step creativity down while identity is below the floor,
        # keeping the best-scoring face. None similarity = no detectable face, so
        # we can't tell and leave the first result alone.
        sim = analysis.identity_similarity(crop, enhanced)
        attempts = 0
        while sim is not None and sim < IDENTITY_MIN and attempts < IDENTITY_MAX_RETRIES:
            attempts += 1
            creativity *= IDENTITY_RETRY_FACTOR
            candidate = await self._face_pass(crop, seed, creativity)
            candidate_sim = analysis.identity_similarity(crop, candidate)
            if candidate_sim is None:
                break
            if candidate_sim > sim:
                enhanced, sim = candidate, candidate_sim
        state.artifacts.setdefault("face_identity", []).append(
            {
                "box": list(box),
                "similarity": round(sim, 3) if sim is not None else None,
                "attempts": attempts,
            }
        )
        if sim is not None and sim < IDENTITY_MIN:
            logger.warning(
                "identity gate: face %s stayed at %.3f (< %.2f) after %d retries",
                box, sim, IDENTITY_MIN, attempts,
            )

        target = (int(box[0] * sx), int(box[1] * sy), int(box[2] * sx), int(box[3] * sy))
        size = (target[2] - target[0], target[3] - target[1])
        enhanced = enhanced.resize(size, Image.LANCZOS)  # 4x -> target = supersampled
        image.paste(enhanced, target[:2], feathered_mask(size, pad=24, radius=70, blur=24))
        return image
