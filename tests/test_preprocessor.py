"""Preprocessor denoise: strength follows the Analyzer's noise level."""

import numpy as np
from PIL import Image

from app.pipeline.analysis import noise_level
from app.pipeline.base import PipelineState
from app.pipeline.context import ImageContext
from app.pipeline.stages.preprocessor import Preprocessor


def noisy_image(sigma: float, size: int = 128) -> Image.Image:
    rng = np.random.default_rng(7)
    base = np.full((size, size, 3), 128.0)
    noisy = base + rng.normal(0, sigma, base.shape)
    return Image.fromarray(np.clip(noisy, 0, 255).astype(np.uint8))


def make_state(img: Image.Image, noise: str) -> PipelineState:
    state = PipelineState(original=img)
    state.context = ImageContext(width=img.width, height=img.height, noise=noise)
    return state


def sigma_of(img: Image.Image) -> float:
    import cv2, math

    gray = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY).astype(np.float64)
    h, w = gray.shape
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)
    s = np.abs(cv2.filter2D(gray, -1, kernel)).sum()
    return s * math.sqrt(0.5 * math.pi) / (6.0 * (w - 2) * (h - 2))


async def test_high_noise_gets_denoised():
    img = noisy_image(sigma=12)
    assert noise_level(np.asarray(img)[:, :, ::-1]) == "high"

    out = await Preprocessor().process(img, make_state(img, "high"))

    assert sigma_of(out) < sigma_of(img) / 2  # substantially cleaner
    assert out.size == img.size


async def test_low_noise_is_untouched():
    img = noisy_image(sigma=1)
    out = await Preprocessor().process(img, make_state(img, "low"))
    assert np.array_equal(np.asarray(out), np.asarray(img))


async def test_no_context_skips_denoise():
    img = noisy_image(sigma=12)
    out = await Preprocessor().process(img, PipelineState(original=img))
    assert np.array_equal(np.asarray(out), np.asarray(img))
