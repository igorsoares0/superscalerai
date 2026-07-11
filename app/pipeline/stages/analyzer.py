"""Stage 1: Analyzer — worker CPU, no GPU calls (SPEC.md)."""

import numpy as np
from PIL import Image

from app.pipeline import analysis
from app.pipeline.base import PipelineStage, PipelineState
from app.pipeline.context import ImageContext


class Analyzer(PipelineStage):
    name = "analyzer"

    # a face taking at least this fraction of frame height is a close-up:
    # the generative pass handles it well and no local repair is needed
    CLOSEUP_FACE_FRACTION = 0.4

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        rgb = np.asarray(image.convert("RGB"))
        bgr = rgb[:, :, ::-1].copy()

        faces = analysis.detect_faces(bgr)
        image_type = None
        if faces:
            largest = max((b[3] - b[1]) / image.height for b in faces)
            image_type = "portrait" if largest >= self.CLOSEUP_FACE_FRACTION else "people"

        state.context = ImageContext(
            width=image.width,
            height=image.height,
            image_type=image_type,
            faces=faces,
            text_regions=analysis.detect_text_regions(bgr, exclude=faces),
            blur=analysis.blur_level(bgr),
            noise=analysis.noise_level(bgr),
            compression=(image.format or "").lower() or None,
        )
        return image
