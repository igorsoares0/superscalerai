import logging
import time

from PIL import Image

from app.pipeline.base import PipelineStage, PipelineState

logger = logging.getLogger(__name__)


class PipelineEngine:
    """Runs stages in sequence, timing and logging each one."""

    def __init__(self, stages: list[PipelineStage]):
        self.stages = stages

    async def run(self, image: Image.Image) -> PipelineState:
        state = PipelineState(original=image.copy())
        current = image
        for stage in self.stages:
            start = time.monotonic()
            current = await stage.process(current, state)
            elapsed = time.monotonic() - start
            state.stage_timings[stage.name] = elapsed
            logger.info("stage %s finished in %.1fs", stage.name, elapsed)
        state.artifacts["final"] = current
        return state
