"""Presets are parameter bundles (SPEC.md: Planner).

denoise maps to Clarity's `creativity`, guidance to `resemblance`.
Ranges validated manually on 2026-07-10; systematic calibration pending
(SPEC.md: Quality Roadmap item 1).
"""

from pydantic import BaseModel

BASE_PROMPT = (
    "masterpiece, best quality, highres, {caption}, "
    "<lora:more_details:0.5> <lora:SDXLrender_v2.0:1>"
)


class Preset(BaseModel):
    name: str
    denoise: float
    guidance: float
    local_enhancers: list[str]


PRESETS: dict[str, Preset] = {
    "portrait": Preset(name="portrait", denoise=0.28, guidance=0.8, local_enhancers=["face"]),
    "product": Preset(name="product", denoise=0.25, guidance=0.9, local_enhancers=["protect_text"]),
    "architecture": Preset(name="architecture", denoise=0.35, guidance=0.8, local_enhancers=["protect_text"]),
    "ai-generated": Preset(name="ai-generated", denoise=0.50, guidance=0.6, local_enhancers=["face"]),
}
