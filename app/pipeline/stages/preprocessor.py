"""Stage 4: Preprocessor — worker CPU (SPEC.md).

Takes the color/tone snapshot of the ORIGINAL before any normalization,
used later by the Post Processor's color match.
"""

from PIL import Image, ImageOps

from app.pipeline.base import PipelineStage, PipelineState


class Preprocessor(PipelineStage):
    name = "preprocessor"

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        state.color_reference = image.copy()
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        # TODO: noise reduction, JPEG artifact removal, normalization
        return image
