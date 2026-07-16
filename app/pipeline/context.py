"""Data passed between pipeline stages (SPEC.md: Pipeline Stages)."""

from pydantic import BaseModel, Field

Box = tuple[int, int, int, int]  # x0, y0, x1, y1 in original-image pixels


class ImageContext(BaseModel):
    """Measured facts about the input image, produced by the Analyzer."""

    width: int
    height: int
    image_type: str | None = None
    noise: str | None = None
    blur: str | None = None
    compression: str | None = None
    faces: list[Box] = Field(default_factory=list)
    text_regions: list[Box] = Field(default_factory=list)
    caption: str | None = None


class ExecutionPlan(BaseModel):
    """Preset + ImageContext + job options resolved into concrete parameters.

    Stored on the job (jobs.params) for reproducibility.
    """

    preset: str
    scale_factor: float
    passes: int
    denoise: float
    guidance: float
    hdr: float = 6.0  # Clarity `dynamic`, its default
    prompt: str
    seed: int
    local_enhancers: list[str] = Field(default_factory=list)
    protect_regions: list[Box] = Field(default_factory=list)
    face_regions: list[Box] = Field(default_factory=list)
