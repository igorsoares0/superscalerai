import pytest
from PIL import Image, ImageDraw

from app.pipeline.engine import PipelineEngine
from app.pipeline.stages import Analyzer


async def _analyze(image: Image.Image):
    state = await PipelineEngine([Analyzer()]).run(image)
    assert state.context is not None
    return state.context


@pytest.mark.asyncio
async def test_plain_image_has_no_detections():
    ctx = await _analyze(Image.new("RGB", (400, 300), "gray"))
    assert ctx.faces == []
    assert ctx.text_regions == []
    assert ctx.blur == "high"  # flat image has no edges


@pytest.mark.asyncio
async def test_text_block_is_detected():
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(["PRODUCT LABEL TEXT", "MODEL XYZ-123 EDITION"]):
        draw.text((250, 260 + i * 30), line, fill="black")
    ctx = await _analyze(image)
    assert ctx.text_regions, "expected at least one text region"
    x0, y0, x1, y1 = ctx.text_regions[0]
    assert x0 < 280 < x1 and y0 < 270 < y1  # box covers the drawn text
