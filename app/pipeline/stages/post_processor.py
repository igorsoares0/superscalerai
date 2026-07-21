"""Stage 7: Post Processor — worker CPU (SPEC.md).

Wavelet color match: the generative upscaler drifts global tone (white
balance, saturation, contrast) away from the original. We split both
images into frequency bands with progressive Gaussian blurs and rebuild
the result from the upscale's high frequencies (detail) plus the
original's low frequencies (color/tone). Local by construction, so it
also fixes tone drift that varies across the frame.

Sharpening (2026-07-21): gentle unsharp gated by local gradient (flat
regions — sky, bokeh — keep their noise unamplified) with the classic
anti-ringing clamp: no pixel may leave the [erode, dilate] envelope of
its 3x3 neighborhood, which is exactly the overshoot that reads as a
halo along strong edges.

Seam scan (2026-07-21): the provider tiles internally and its contract
is "no visible seams" — this verifies it. A tile seam is a sustained
column/row discontinuity in the OUTPUT that has no counterpart in the
original, so both profiles are compared at the same scale. Diagnostics
only: logs and records to state.artifacts, never fails the job.
"""

import logging

import cv2
import numpy as np
from PIL import Image

from app.pipeline.base import PipelineStage, PipelineState

logger = logging.getLogger(__name__)

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


def sharpen(image: Image.Image, amount: float = 0.5, sigma: float = 1.2) -> Image.Image:
    """Gradient-gated unsharp mask with a halo-suppressing clamp."""
    img = np.asarray(image.convert("RGB"), dtype=np.float32)
    blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=sigma, borderType=cv2.BORDER_REPLICATE)

    # gate: 0 in flat regions, 1 on real structure (soft ramp between)
    gray = cv2.cvtColor(blurred, cv2.COLOR_RGB2GRAY)
    grad = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    gate = np.clip((grad - 4.0) / 12.0, 0.0, 1.0)[..., None]

    sharpened = img + amount * gate * (img - blurred)

    # anti-ringing: overshoot past the 3x3 neighborhood extremes IS the halo
    kernel = np.ones((3, 3), np.uint8)
    lo = cv2.erode(img, kernel)
    hi = cv2.dilate(img, kernel)
    return Image.fromarray(np.clip(sharpened, lo, hi).astype(np.uint8))


def seam_scan(
    image: Image.Image,
    reference: Image.Image,
    step: float = 3.0,
    frac_threshold: float = 0.6,
) -> list[dict]:
    """Tile seams: full-length discontinuities that exist only in the output.

    A seam is COHERENT — most rows step across the same column (or rows,
    transposed) — while a natural edge is partial or lives in the
    reference too. Magnitude-based scoring flagged every crisp generative
    edge (890 false positives on one photo); the coherent-fraction form
    scores zero false positives on the validation outputs and catches a
    6-gray-level synthetic seam. `reference`: the original, any size.
    Returns [{"axis": "x"|"y", "position": int, "frac": float}, ...].
    """
    out = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY).astype(np.float32)
    ref = reference.convert("RGB").resize(image.size, Image.LANCZOS)
    ref_g = cv2.cvtColor(np.asarray(ref), cv2.COLOR_RGB2GRAY).astype(np.float32)

    seams: list[dict] = []
    for axis, name in ((1, "x"), (0, "y")):
        out_step = np.abs(np.diff(out, axis=axis)) > step
        ref_flat = np.abs(np.diff(ref_g, axis=axis)) < step / 2
        frac = (out_step & ref_flat).mean(axis=1 - axis)
        for pos in np.nonzero(frac > frac_threshold)[0]:
            # ignore the frame borders: exporters/resizes touch them
            if 8 < pos < len(frac) - 8:
                seams.append({"axis": name, "position": int(pos), "frac": round(float(frac[pos]), 2)})
    return seams


class PostProcessor(PipelineStage):
    name = "post_processor"

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        if state.color_reference is not None:
            image = color_match(image, state.color_reference)
        image = sharpen(image)
        seams = seam_scan(image, state.color_reference or state.original)
        if seams:
            state.artifacts["seams"] = seams
            logger.warning("possible tile seams in output: %s", seams[:10])
        return image
