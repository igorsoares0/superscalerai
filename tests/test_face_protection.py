"""Item 2 (2026-07-24): decouple the background creativity from the face.

At low main-pass creativity the generative pass handles close-ups, so only
small faces are repaired. When the background runs "hot" (high creativity,
for a Magnific-style wow), EVERY face is routed to the dedicated
low-creativity repair pass so identity is preserved regardless of face size.
"""

import io
from typing import Any

from PIL import Image

from app.pipeline.base import PipelineState
from app.pipeline.context import ExecutionPlan, ImageContext
from app.pipeline.stages.local_enhancers import LocalEnhancers
from app.pipeline.stages.planner import Planner
from app.providers.base import AIProvider

SMALL_FACE = (10, 10, 30, 30)    # 20px tall on a 100px frame -> 0.2 < 0.4
CLOSEUP_FACE = (10, 10, 90, 90)  # 80px tall -> 0.8, a close-up


def _state_with_faces() -> PipelineState:
    state = PipelineState(original=Image.new("RGB", (100, 100)))
    state.context = ImageContext(
        width=100, height=100, caption="a person", faces=[SMALL_FACE, CLOSEUP_FACE]
    )
    return state


async def test_low_creativity_repairs_only_small_faces():
    state = _state_with_faces()
    await Planner("portrait").process(state.original, state)  # denoise 0.20
    assert state.plan.denoise == 0.20
    assert state.plan.face_regions == [SMALL_FACE]  # close-up left to the main pass


async def test_hot_background_repairs_every_face():
    state = _state_with_faces()
    await Planner("portrait", options={"creativity": 0.5}).process(state.original, state)
    assert state.plan.denoise == 0.5
    # both faces protected: the hot background pass can't touch identity
    assert state.plan.face_regions == [SMALL_FACE, CLOSEUP_FACE]
    assert "face" in state.plan.local_enhancers


class _FaceGen(AIProvider):
    """Records the generative-upscaler call made for the face crop."""

    def __init__(self):
        self.gen_input: dict[str, Any] | None = None

    async def run(self, model: str, input: dict[str, Any]) -> Any:
        assert model == "generative-upscaler"
        self.gen_input = input
        return {"output": ["url"], "metrics": {"predict_time": 0.1}}

    async def upload(self, data: bytes, filename: str) -> str:
        self._crop = Image.open(io.BytesIO(data)).size
        return "data:image/png;base64,fake"

    async def download(self, url: str) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (self._crop[0] * 4, self._crop[1] * 4), "red").save(buf, format="PNG")
        return buf.getvalue()


async def test_face_pass_uses_plan_face_creativity():
    provider = _FaceGen()
    state = PipelineState(original=Image.new("RGB", (100, 100), "blue"))
    state.plan = ExecutionPlan(
        preset="portrait", scale_factor=2, passes=1, denoise=0.5, guidance=0.75,
        prompt="x", seed=7, face_regions=[CLOSEUP_FACE], face_creativity=0.10,
    )
    await LocalEnhancers(provider).process(Image.new("RGB", (200, 200), "green"), state)

    assert provider.gen_input is not None
    # face stays on its own low creativity, independent of the 0.5 background...
    assert provider.gen_input["creativity"] == 0.10
    assert provider.gen_input["seed"] == 7  # ...and deterministic with the job


async def test_planner_plumbs_preset_face_creativity_into_plan():
    state = _state_with_faces()
    await Planner("portrait").process(state.original, state)
    assert state.plan.face_creativity == 0.10  # from the preset, stored for reproducibility
