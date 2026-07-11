"""Stage 8: Exporter — final image, thumbnail, metadata (SPEC.md)."""

import json
from pathlib import Path

from PIL import Image

from app.core.config import settings
from app.pipeline.base import PipelineStage, PipelineState

THUMB_SIZE = (512, 512)


class Exporter(PipelineStage):
    name = "exporter"

    def __init__(self, job_id: str):
        self.job_id = job_id

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        out_dir = Path(settings.storage_dir) / "jobs" / self.job_id
        out_dir.mkdir(parents=True, exist_ok=True)

        image.save(out_dir / "enhanced.png", optimize=True)
        thumb = image.copy()
        thumb.thumbnail(THUMB_SIZE)
        thumb.save(out_dir / "thumb.jpg", quality=85)

        assert state.plan is not None
        (out_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "plan": state.plan.model_dump(),
                    "context": state.context.model_dump() if state.context else None,
                    "stage_timings": state.stage_timings,
                },
                indent=2,
            )
        )
        state.artifacts["enhanced_path"] = str(out_dir / "enhanced.png")
        state.artifacts["thumb_path"] = str(out_dir / "thumb.jpg")
        return image
