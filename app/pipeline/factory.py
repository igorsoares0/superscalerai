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
from app.pipeline.presets import PRESETS
from app.providers.base import AIProvider
from app.providers.replicate import ReplicateProvider


def build_pipeline(
    job_id: str,
    preset: str,
    scale_factor: float = 2,
    seed: int | None = None,
    options: dict | None = None,
    provider: AIProvider | None = None,
) -> PipelineEngine:
    provider = provider or ReplicateProvider()
    return PipelineEngine(
        [
            Analyzer(),
            # the OCR pass only pays off where its boxes get used
            Captioner(provider, ocr="protect_text" in PRESETS[preset].local_enhancers),
            Planner(preset, scale_factor, seed, options),
            Preprocessor(),
            GenerativeUpscaler(provider),
            LocalEnhancers(provider),
            PostProcessor(),
            Exporter(job_id),
        ]
    )
