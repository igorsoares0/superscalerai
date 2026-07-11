from app.pipeline.engine import PipelineEngine
from app.pipeline.stages import (
    Analyzer,
    Captioner,
    Exporter,
    GenerativeUpscaler,
    LocalEnhancers,
    Planner,
    PostProcessor,
    Preprocessor,
)
from app.providers.base import AIProvider
from app.providers.replicate import ReplicateProvider


def build_pipeline(
    job_id: str,
    preset: str,
    scale_factor: float = 2,
    seed: int | None = None,
    provider: AIProvider | None = None,
) -> PipelineEngine:
    provider = provider or ReplicateProvider()
    return PipelineEngine(
        [
            Analyzer(),
            Captioner(provider),
            Planner(preset, scale_factor, seed),
            Preprocessor(),
            GenerativeUpscaler(provider),
            LocalEnhancers(provider),
            PostProcessor(),
            Exporter(job_id),
        ]
    )
