"""Wavelet color match (PostProcessor): color from the original,
detail from the upscale."""

import numpy as np
from PIL import Image

from app.pipeline.base import PipelineState
from app.pipeline.stages.post_processor import PostProcessor, color_match


def smooth_reference(size: int = 96) -> Image.Image:
    """A smooth two-axis gradient — pure low-frequency content."""
    x = np.linspace(40, 210, size, dtype=np.float32)
    y = np.linspace(60, 180, size, dtype=np.float32)
    r = np.tile(x, (size, 1))
    g = np.tile(y[:, None], (1, size))
    b = np.full((size, size), 120, dtype=np.float32)
    return Image.fromarray(np.stack([r, g, b], axis=-1).astype(np.uint8))


def cast(img: Image.Image, dr: int, dg: int, db: int) -> Image.Image:
    arr = np.asarray(img, dtype=np.int16) + np.array([dr, dg, db])
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def test_color_match_removes_color_cast():
    ref = smooth_reference()
    upscaled = cast(ref.resize((192, 192), Image.LANCZOS), 35, -25, 15)

    matched = color_match(upscaled, ref)

    target = np.asarray(ref.resize((192, 192), Image.LANCZOS), dtype=np.float32)
    got = np.asarray(matched, dtype=np.float32)
    before = np.asarray(upscaled, dtype=np.float32)
    assert abs(before - target).mean() > 20  # the cast was real
    assert abs(got - target).mean() < 3  # and the match removed it


def test_color_match_keeps_high_frequency_detail():
    ref = smooth_reference()
    up = np.asarray(ref.resize((192, 192), Image.LANCZOS), dtype=np.float32)
    checker = (np.indices((192, 192)).sum(axis=0) % 2) * 24.0 - 12.0
    detailed = Image.fromarray(np.clip(up + checker[..., None], 0, 255).astype(np.uint8))

    matched = np.asarray(color_match(detailed, ref), dtype=np.float32)

    # the pixel-to-pixel checkerboard contrast survives the color match
    contrast = abs(np.diff(matched[:, :, 0], axis=1)).mean()
    assert contrast > 15


async def test_post_processor_without_reference_is_identity():
    img = smooth_reference()
    state = PipelineState(original=img)
    out = await PostProcessor().process(img, state)
    assert out is img
