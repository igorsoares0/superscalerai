"""Stage 8: Exporter — final image, thumbnail, metadata (SPEC.md)."""

import io
import json

from PIL import Image

from app.pipeline.base import PipelineStage, PipelineState
from app.services.storage import get_storage

THUMB_SIZE = (512, 512)


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


class Exporter(PipelineStage):
    name = "exporter"

    def __init__(self, job_id: str):
        self.job_id = job_id

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        storage = get_storage()
        prefix = f"jobs/{self.job_id}"

        storage.put(f"{prefix}/enhanced.png", _png_bytes(image))

        thumb = image.copy()
        thumb.thumbnail(THUMB_SIZE)
        thumb_buf = io.BytesIO()
        thumb.convert("RGB").save(thumb_buf, format="JPEG", quality=85)
        storage.put(f"{prefix}/thumb.jpg", thumb_buf.getvalue())

        assert state.plan is not None
        metadata = json.dumps(
            {
                "plan": state.plan.model_dump(),
                "context": state.context.model_dump() if state.context else None,
                "stage_timings": state.stage_timings,
            },
            indent=2,
        )
        storage.put(f"{prefix}/metadata.json", metadata.encode())

        state.artifacts["enhanced_path"] = f"{prefix}/enhanced.png"
        state.artifacts["thumb_path"] = f"{prefix}/thumb.jpg"
        return image
