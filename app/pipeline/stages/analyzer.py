"""Stage 1: Analyzer — worker CPU, no GPU calls (SPEC.md)."""

from PIL import Image

from app.pipeline.base import PipelineStage, PipelineState
from app.pipeline.context import ImageContext


class Analyzer(PipelineStage):
    name = "analyzer"

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        state.context = ImageContext(width=image.width, height=image.height)
        # TODO: face detection (OpenCV YuNet) -> context.faces
        # TODO: text detection -> context.text_regions
        # TODO: noise / blur / compression estimates
        return image
