"""Guards that the Generative Upscaler sends the PREPROCESSED image to Clarity.

Pipeline order: Captioner -> Planner -> Preprocessor -> GenerativeUpscaler.
The Captioner uploads the raw image (for captioning); the Preprocessor then
denoises. A previous bug had the GenerativeUpscaler reuse the captioner's
cached raw URL, so Clarity received the un-denoised image — defeating the
Preprocessor's purpose ("keep Clarity from hallucinating texture on top of
sensor noise"). This drives a high-noise image (so the denoise measurably
changes pixels) and checks the bytes that reach the generative call.
"""

import io
from typing import Any

import numpy as np
import pytest
from PIL import Image

from app.pipeline.base import PipelineState
from app.pipeline.engine import PipelineEngine
from app.pipeline.stages import Analyzer, Captioner, GenerativeUpscaler, Planner, Preprocessor
from app.providers.replicate import ReplicateProvider


def _png(size=(8, 8)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "black").save(buf, format="PNG")
    return buf.getvalue()


class RecordingProvider(ReplicateProvider):
    """Subclasses ReplicateProvider (the generative stage asserts that type)
    but overrides every network method. Records uploads by URL and the URL
    the generative call receives."""

    def __init__(self):
        self.uploads: dict[str, bytes] = {}
        self._n = 0
        self.first_upload_url: str | None = None
        self.generative_input_url: str | None = None

    async def upload(self, data: bytes, filename: str) -> str:
        self._n += 1
        url = f"fake://upload/{self._n}"
        self.uploads[url] = data
        if self.first_upload_url is None:
            self.first_upload_url = url
        return url

    async def run(self, model: str, input: dict[str, Any]) -> Any:
        if model == "captioner":
            return {
                "output": {"img": None, "text": "{'<DETAILED_CAPTION>': 'noise'}"},
                "metrics": {"predict_time": 0.1},
            }
        if model == "generative-upscaler":
            self.generative_input_url = input["image"]
            return {"output": ["fake://output/1"], "metrics": {"predict_time": 1.0}}
        raise NotImplementedError(model)

    async def download(self, url: str) -> bytes:
        return _png()


def _mean_abs_diff(a: Image.Image, b: Image.Image) -> float:
    return float(
        np.abs(
            np.asarray(a.convert("RGB"), dtype=np.float32)
            - np.asarray(b.convert("RGB"), dtype=np.float32)
        ).mean()
    )


@pytest.mark.asyncio
async def test_generative_upscaler_receives_preprocessed_image():
    # A smooth base (upscaled low-res random) with additive noise on top —
    # this is where NLM denoise actually bites, unlike pure white noise.
    rng = np.random.default_rng(0)
    base = Image.fromarray(rng.integers(0, 256, (8, 8, 3), dtype=np.uint8), "RGB").resize(
        (128, 128), Image.BILINEAR
    )
    noisy = np.asarray(base, dtype=np.float32) + rng.normal(0, 25, (128, 128, 3))
    raw = Image.fromarray(np.clip(noisy, 0, 255).astype(np.uint8), "RGB")

    provider = RecordingProvider()
    engine = PipelineEngine(
        [
            Analyzer(),
            Captioner(provider),
            Planner("portrait", seed=42),
            Preprocessor(),
            GenerativeUpscaler(provider),
        ]
    )
    await engine.run(raw.copy())

    # Independently reproduce what the Preprocessor would hand downstream.
    ref = PipelineState(original=raw.copy())
    await Analyzer().process(raw.copy(), ref)
    assert ref.context is not None and ref.context.noise in ("medium", "high")
    denoised = await Preprocessor().process(raw.copy(), ref)

    # The generative stage uploads its own (preprocessed) image rather than
    # reusing the captioner's raw upload: two distinct uploads.
    assert len(provider.uploads) == 2
    assert provider.generative_input_url != provider.first_upload_url

    # Compare against BOTH candidates put through the captioner's exact JPEG
    # q90 encode, so the JPEG re-compression is not what distinguishes them —
    # only whether the denoise was applied.
    def enc(img: Image.Image) -> Image.Image:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=90)
        return Image.open(io.BytesIO(buf.getvalue()))

    raw_ref, denoised_ref = enc(raw), enc(denoised)
    assert _mean_abs_diff(raw_ref, denoised_ref) > 1.0, "denoise must be distinguishable"

    sent = Image.open(io.BytesIO(provider.uploads[provider.generative_input_url]))
    dist_to_raw = _mean_abs_diff(sent, raw_ref)
    dist_to_denoised = _mean_abs_diff(sent, denoised_ref)

    # Desired behavior: Clarity should receive the DENOISED image, so `sent`
    # should match `denoised_ref`. Fails today because it receives the raw one.
    assert dist_to_denoised < dist_to_raw, (
        "Generative Upscaler sent the RAW image to Clarity, not the "
        f"preprocessed/denoised one: dist(sent, raw)={dist_to_raw:.3f} "
        f"vs dist(sent, denoised)={dist_to_denoised:.3f}"
    )
