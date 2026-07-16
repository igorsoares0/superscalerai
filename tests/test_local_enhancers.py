"""LocalEnhancers: protected regions come back from the deterministic
upscaler (Real-ESRGAN), with Lanczos as the failure fallback."""

import io
from typing import Any

from PIL import Image

from app.pipeline.base import PipelineState
from app.pipeline.context import ExecutionPlan
from app.pipeline.stages.local_enhancers import LocalEnhancers
from app.providers.base import AIProvider

# big enough that the feathered mask reaches full opacity at the center
BOX = (10, 10, 90, 90)


class FakeEsrgan(AIProvider):
    """Returns a solid red patch so composited pixels are recognizable."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, model: str, input: dict[str, Any]) -> Any:
        self.calls.append((model, input))
        if self.fail:
            raise RuntimeError("provider down")
        return {"output": "fake-url"}

    async def upload(self, data: bytes, filename: str) -> str:
        self.crop_size = Image.open(io.BytesIO(data)).size
        return "data:image/png;base64,fake"

    async def download(self, url: str) -> bytes:
        scale = self.calls[-1][1]["scale"]
        size = (self.crop_size[0] * scale, self.crop_size[1] * scale)
        buf = io.BytesIO()
        Image.new("RGB", size, "red").save(buf, format="PNG")
        return buf.getvalue()


def make_state() -> PipelineState:
    state = PipelineState(original=Image.new("RGB", (100, 100), "blue"))
    state.plan = ExecutionPlan(
        preset="portrait", scale_factor=2, passes=1, denoise=0.28,
        guidance=0.75, prompt="x", seed=1, protect_regions=[BOX],
    )
    return state


async def test_protected_region_uses_deterministic_upscaler():
    provider = FakeEsrgan()
    upscaled = Image.new("RGB", (200, 200), "green")
    out = await LocalEnhancers(provider).process(upscaled, make_state())

    model, params = provider.calls[0]
    assert model == "deterministic-upscaler"
    assert params["scale"] == 4  # 2x job still requests 4x = supersampled
    assert params["face_enhance"] is False  # GFPGAN license-blocked

    r, g, b = out.getpixel((100, 100))  # center of the 2x target region
    assert r > 200 and g < 60  # red patch from the fake provider
    assert out.getpixel((5, 5)) == (0, 128, 0)  # outside: untouched green


async def test_protected_region_falls_back_to_lanczos_on_failure():
    provider = FakeEsrgan(fail=True)
    upscaled = Image.new("RGB", (200, 200), "green")
    out = await LocalEnhancers(provider).process(upscaled, make_state())

    r, g, b = out.getpixel((100, 100))
    assert b > 200 and r < 60  # blue = Lanczos of the original crop
    assert out.getpixel((5, 5)) == (0, 128, 0)
