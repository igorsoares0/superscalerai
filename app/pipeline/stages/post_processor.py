"""Stage 7: Post Processor — worker CPU (SPEC.md).

Wavelet color match: the generative upscaler drifts global tone (white
balance, saturation, contrast) away from the original. We split both
images into frequency bands with progressive Gaussian blurs and rebuild
the result from the upscale's high frequencies (detail) plus the
original's low frequencies (color/tone). Local by construction, so it
also fixes tone drift that varies across the frame.
"""

import cv2
import numpy as np
from PIL import Image

from app.pipeline.base import PipelineStage, PipelineState

WAVELET_LEVELS = 5


def _decompose(image: np.ndarray, levels: int) -> tuple[np.ndarray, np.ndarray]:
    """Split into (high_freq, low_freq); summing them restores the input."""
    high = np.zeros_like(image)
    low = image
    for level in range(1, levels + 1):
        blurred = cv2.GaussianBlur(
            low, (0, 0), sigmaX=2**level, borderType=cv2.BORDER_REPLICATE
        )
        high += low - blurred
        low = blurred
    return high, low


def color_match(image: Image.Image, reference: Image.Image) -> Image.Image:
    """Detail from `image`, color/tone from `reference` (any size)."""
    ref = reference.convert("RGB").resize(image.size, Image.LANCZOS)
    img_arr = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    ref_arr = np.asarray(ref, dtype=np.float32) / 255.0

    high, _ = _decompose(img_arr, WAVELET_LEVELS)
    _, low = _decompose(ref_arr, WAVELET_LEVELS)
    out = np.clip((high + low) * 255.0, 0.0, 255.0).astype(np.uint8)
    return Image.fromarray(out)


class PostProcessor(PipelineStage):
    name = "post_processor"

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        if state.color_reference is not None:
            image = color_match(image, state.color_reference)
        # TODO: calibrated sharpening, halo removal, seam inspection
        return image
