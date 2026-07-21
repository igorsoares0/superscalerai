"""Florence-2 OCR text regions: parsing, filtering, and Captioner wiring.

The quad/label fixtures are real outputs captured from the pinned model
on the validation photos (2026-07-21) — including the hallucinated
non-Latin digit labels it emits on textless images.
"""

from typing import Any

import pytest
from PIL import Image

from app.pipeline.analysis import ocr_text_regions
from app.pipeline.engine import PipelineEngine
from app.pipeline.stages import Analyzer, Captioner
from app.pipeline.stages.captioner import parse_ocr_regions
from app.providers.base import AIProvider

CSZ_QUAD = [721.6, 504.7, 773.0, 506.6, 773.0, 518.0, 721.6, 516.1]  # "New Balance", 1318x1894 photo


def test_real_logo_survives_filters_padded_and_clamped():
    boxes = ocr_text_regions([(CSZ_QUAD, "</s>New Balance")], 1318, 1894)
    assert len(boxes) == 1
    x0, y0, x1, y1 = boxes[0]
    assert x0 < 721 and y0 < 504 and x1 > 773 and y1 > 518  # padded beyond the quad
    assert x0 >= 0 and y1 <= 1894


def test_hallucinated_digit_labels_are_dropped():
    tst = ([850.3, 1171.8, 864.6, 1171.8, 864.6, 1187.0, 850.3, 1187.0], "</s>٠٠")
    degraded = ([144.9, 270.6, 144.9, 321.2, 131.1, 321.2, 131.1, 270.6], "</s>٠١٢٠")
    assert ocr_text_regions([tst], 1792, 2176) == []
    assert ocr_text_regions([degraded], 329, 322) == []


def test_tiny_area_is_dropped_even_with_real_glyphs():
    # a real-glyph label whose box is below the 0.01% floor
    speck = ([10, 10, 22, 10, 22, 16, 10, 16], "</s>ok")
    assert ocr_text_regions([speck], 4000, 4000) == []


def test_overlapping_lines_merge():
    line1 = [100, 100, 300, 100, 300, 130, 100, 130]
    line2 = [100, 140, 300, 140, 300, 170, 100, 170]  # padding makes them overlap
    boxes = ocr_text_regions([(line1, "</s>FIRST LINE"), (line2, "</s>SECOND LINE")], 800, 600)
    assert len(boxes) == 1


def test_parse_ocr_regions_real_shape_and_garbage():
    out = {
        "img": None,
        "text": "{'<OCR_WITH_REGION>': {'quad_boxes': [%r], 'labels': ['</s>New Balance']}}" % (CSZ_QUAD,),
    }
    regions = parse_ocr_regions(out, 1318, 1894)
    assert regions is not None and len(regions) == 1
    assert parse_ocr_regions({"text": "not a dict"}, 100, 100) is None
    assert parse_ocr_regions("plain string", 100, 100) is None


class FakeProvider(AIProvider):
    def __init__(self, ocr_output: Any = None, ocr_error: bool = False):
        self.ocr_output = ocr_output
        self.ocr_error = ocr_error
        self.tasks: list[str] = []

    async def run(self, model: str, input: dict[str, Any]) -> Any:
        assert model == "captioner"
        self.tasks.append(input["task_input"])
        if input["task_input"] == "Detailed Caption":
            return {"output": {"img": None, "text": "{'<DETAILED_CAPTION>': 'a product photo'}"}}
        if self.ocr_error:
            raise RuntimeError("prediction failed")
        return {"output": self.ocr_output}

    async def upload(self, data: bytes, filename: str) -> str:
        return "data:image/png;base64,fake"


async def run_captioner(provider: FakeProvider, ocr: bool):
    engine = PipelineEngine([Analyzer(), Captioner(provider, ocr=ocr)])
    return await engine.run(Image.new("RGB", (1318, 1894), "salmon"))


@pytest.mark.asyncio
async def test_ocr_boxes_replace_heuristic_regions():
    provider = FakeProvider(
        ocr_output={
            "img": None,
            "text": "{'<OCR_WITH_REGION>': {'quad_boxes': [%r], 'labels': ['</s>New Balance']}}" % (CSZ_QUAD,),
        }
    )
    state = await run_captioner(provider, ocr=True)
    assert sorted(provider.tasks) == ["Detailed Caption", "OCR with Region"]
    assert state.context is not None
    assert len(state.context.text_regions) == 1
    assert state.context.caption == "a product photo"


@pytest.mark.asyncio
async def test_ocr_empty_answer_clears_heuristic_false_positives():
    provider = FakeProvider(
        ocr_output={"img": None, "text": "{'<OCR_WITH_REGION>': {'quad_boxes': [], 'labels': []}}"}
    )
    state = await run_captioner(provider, ocr=True)
    assert state.context is not None and state.context.text_regions == []


@pytest.mark.asyncio
async def test_ocr_failure_keeps_heuristic_regions_and_job_alive():
    provider = FakeProvider(ocr_error=True)
    state = await run_captioner(provider, ocr=True)
    assert state.context is not None
    assert state.context.caption == "a product photo"  # job survived


@pytest.mark.asyncio
async def test_ocr_disabled_makes_single_prediction():
    provider = FakeProvider()
    await run_captioner(provider, ocr=False)
    assert provider.tasks == ["Detailed Caption"]
