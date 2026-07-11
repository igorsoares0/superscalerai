"""Stage interface (SPEC.md: Internal Architecture).

Every stage implements the same interface and must be independently
replaceable. Stages are stateless; everything mutable lives in PipelineState.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from app.pipeline.context import ExecutionPlan, ImageContext


@dataclass
class PipelineState:
    """Mutable state carried through the pipeline for one job."""

    original: Image.Image
    context: ImageContext | None = None
    plan: ExecutionPlan | None = None
    color_reference: Image.Image | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    stage_timings: dict[str, float] = field(default_factory=dict)


class PipelineStage(ABC):
    name: str = "stage"

    @abstractmethod
    async def process(self, image: Image.Image, state: PipelineState) -> Image.Image:
        """Take the current image, return the (possibly replaced) image."""
