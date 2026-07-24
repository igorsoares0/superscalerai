"""EXIF orientation is normalized once, at pipeline entry.

Regression: the Preprocessor used to run exif_transpose at stage 4, after
the Analyzer had already measured face/text boxes and after state.original
was copied — both in the un-rotated space — while later stages (generative
upload, color match) worked in the rotated space. On EXIF-rotated phone
photos that mismatch made the Local Enhancers composite face/text patches
in the wrong place. The fix transposes once in engine.run, before anything
reads the image, so every stage shares one coordinate space.
"""

import io

import pytest
from PIL import Image

from app.pipeline.engine import PipelineEngine
from app.pipeline.stages import Analyzer, Preprocessor


def _exif_rotated_jpeg(size=(100, 60), orientation=6) -> bytes:
    """A JPEG whose stored pixels are `size` but that declares an EXIF
    orientation requiring a 90° transpose for display (so width/height swap
    once applied). PIL does not auto-rotate on open, matching how the worker
    reads the uploaded bytes."""
    img = Image.new("RGB", size, "white")
    exif = img.getexif()
    exif[0x0112] = orientation  # 6 = rotate 90° CW on display
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_pipeline_normalizes_orientation_before_original_and_analyzer():
    stored = Image.open(io.BytesIO(_exif_rotated_jpeg((100, 60), orientation=6)))
    assert stored.size == (100, 60)  # pixels are stored un-rotated

    engine = PipelineEngine([Analyzer(), Preprocessor()])
    state = await engine.run(stored)

    # The engine transposes once, up front: state.original AND the Analyzer's
    # measured dimensions are both in display orientation (dims swapped).
    assert state.original.size == (60, 100)
    assert state.context is not None
    assert (state.context.width, state.context.height) == (60, 100)


@pytest.mark.asyncio
async def test_pipeline_leaves_unrotated_images_untouched():
    plain = Image.new("RGB", (100, 60), "white")  # no EXIF tag

    state = await PipelineEngine([Analyzer(), Preprocessor()]).run(plain)

    assert state.original.size == (100, 60)
    assert state.context is not None
    assert (state.context.width, state.context.height) == (100, 60)
