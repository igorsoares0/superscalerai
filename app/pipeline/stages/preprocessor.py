"""Stage 4: Preprocessor — worker CPU (SPEC.md).

Takes the color/tone snapshot of the original before any tonal
normalization, used later by the Post Processor's color match. The
snapshot comes AFTER exif_transpose so it stays geometrically aligned
with everything downstream.

Denoise: non-local means, strength driven by the Analyzer's measured
noise level. Cleaning before the generative pass keeps Clarity from
hallucinating texture on top of sensor noise / JPEG blocking (NLM
attenuates both). "low" is deliberately left untouched — denoising a
clean image only eats real texture the upscaler could amplify.
"""

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.pipeline.base import PipelineStage, PipelineState

# (h, hColor) per measured level. Luminance stays conservative — NLM wax
# destroys the structure Clarity needs — while chroma can be aggressive:
# color noise is perceptually free to remove. Calibrated 2026-07-16 against
# ground truth (tst.jpg + sigma-9 noise): h=7 wins PSNR but visibly melts
# eyebrows/hairline; h=5 keeps structure at 35.1 dB (vs 29.2 corrupted).
DENOISE_PARAMS = {"medium": (3.0, 7.0), "high": (5.0, 10.0)}


class Preprocessor(PipelineStage):
    name = "preprocessor"

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        state.color_reference = image.copy()

        noise = state.context.noise if state.context else None
        params = DENOISE_PARAMS.get(noise or "")
        if params:
            h, h_color = params
            bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
            cleaned = cv2.fastNlMeansDenoisingColored(bgr, None, h, h_color, 7, 21)
            image = Image.fromarray(cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB))
        return image
