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
BASE_NEGATIVE = "(worst quality, low quality, normal quality:2) JuggernautNegative-neg"


class Preset(BaseModel):
    name: str
    denoise: float
    guidance: float
    local_enhancers: list[str]
    style_terms: str = ""  # appended to the positive prompt
    negative_terms: str = ""  # appended to the negative prompt


PRESETS: dict[str, Preset] = {
    # skin terms validated 2026-07-16 (A/B vs epicrealism checkpoint, which
    # invented moles and broke on degraded dark skin — rejected): they cut
    # the waxy look without inventing features.
    # denoise/guidance calibrated 2026-07-16 on the golden set
    # (validation/calibrate.py): face identity falls off a cliff above
    # creativity 0.20 (SFace 0.8 -> 0.5 at 0.28, different-person territory
    # at 0.45) while detail barely grows; higher resemblance helps identity
    # at zero detail cost
    "portrait": Preset(
        name="portrait",
        denoise=0.20,
        guidance=1.2,
        local_enhancers=["face"],
        style_terms=", detailed skin texture, skin pores, natural skin",
        negative_terms=", plastic skin, waxy skin, airbrushed, smooth skin",
    ),
    "product": Preset(name="product", denoise=0.25, guidance=0.9, local_enhancers=["protect_text"]),
    "architecture": Preset(name="architecture", denoise=0.35, guidance=0.8, local_enhancers=["protect_text"]),
    "ai-generated": Preset(name="ai-generated", denoise=0.50, guidance=0.6, local_enhancers=["face"]),
}
