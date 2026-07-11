"""Stage 3: Planner — preset + ImageContext + job options -> ExecutionPlan.

The user's preset ALWAYS selects the pipeline; the Analyzer only tunes
parameters within it (SPEC.md).
"""

import random

from PIL import Image

from app.pipeline.base import PipelineStage, PipelineState
from app.pipeline.context import ExecutionPlan
from app.pipeline.presets import BASE_PROMPT, PRESETS


class Planner(PipelineStage):
    name = "planner"

    def __init__(self, preset: str, scale_factor: float = 2, seed: int | None = None):
        self.preset = PRESETS[preset]
        self.scale_factor = scale_factor
        self.seed = seed if seed is not None else random.randint(0, 2**31)

    # faces smaller than this fraction of frame height get degraded by the
    # generative pass and need zoom-and-enhance repair (validated 2026-07-10)
    FACE_REPAIR_FRACTION = 0.4

    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        ctx = state.context
        assert ctx is not None
        # SPEC.md Progressive Scaling: max 2x per generative pass
        passes = max(1, round(self.scale_factor / 2))
        repair_faces = [
            b for b in ctx.faces if (b[3] - b[1]) / ctx.height < self.FACE_REPAIR_FRACTION
        ]
        state.plan = ExecutionPlan(
            preset=self.preset.name,
            scale_factor=self.scale_factor,
            passes=passes,
            denoise=self.preset.denoise,
            guidance=self.preset.guidance,
            prompt=BASE_PROMPT.format(caption=ctx.caption or self.preset.name),
            seed=self.seed,
            local_enhancers=[
                e for e in self.preset.local_enhancers
                if (e == "face" and repair_faces) or (e == "protect_text" and ctx.text_regions)
            ],
            protect_regions=list(ctx.text_regions) if "protect_text" in self.preset.local_enhancers else [],
            face_regions=repair_faces if "face" in self.preset.local_enhancers else [],
        )
        return image
