"""Item 3 (2026-07-24): identity gate on the zoom-and-enhance face pass.

Measures SFace similarity between the original face crop and the enhanced
one; below IDENTITY_MIN it retries once at lower creativity and keeps the
best. The similarity + attempts are recorded per face regardless, so the
gate doubles as a measured identity signal (persisted in metadata.json).

These tests drive the control flow with a stubbed similarity — no GPU and no
SFace model needed; analysis.identity_similarity is a direct port of the
validated calibration harness.
"""

import io
from typing import Any

from PIL import Image

from app.pipeline import analysis
from app.pipeline.base import PipelineState
from app.pipeline.context import ExecutionPlan
from app.pipeline.stages.local_enhancers import LocalEnhancers
from app.providers.base import AIProvider

BOX = (10, 10, 90, 90)


class _GateGen(AIProvider):
    """Records the creativity of each generative face pass."""

    def __init__(self):
        self.creativities: list[float] = []

    async def run(self, model: str, input: dict[str, Any]) -> Any:
        assert model == "generative-upscaler"
        self.creativities.append(input["creativity"])
        return {"output": ["url"], "metrics": {"predict_time": 0.1}}

    async def upload(self, data: bytes, filename: str) -> str:
        self._crop = Image.open(io.BytesIO(data)).size
        return "data:image/png;base64,fake"

    async def download(self, url: str) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (self._crop[0] * 4, self._crop[1] * 4), "red").save(buf, format="PNG")
        return buf.getvalue()


def _state() -> PipelineState:
    state = PipelineState(original=Image.new("RGB", (100, 100), "blue"))
    state.plan = ExecutionPlan(
        preset="portrait", scale_factor=2, passes=1, denoise=0.5, guidance=0.75,
        prompt="x", seed=7, face_regions=[BOX], face_creativity=0.10,
    )
    return state


async def _run(provider, monkeypatch, sims):
    seq = iter(sims)
    monkeypatch.setattr(analysis, "identity_similarity", lambda a, b: next(seq))
    state = _state()
    await LocalEnhancers(provider).process(Image.new("RGB", (200, 200), "green"), state)
    return state


async def test_gate_holds_no_retry(monkeypatch):
    provider = _GateGen()
    state = await _run(provider, monkeypatch, [0.9])
    assert provider.creativities == [0.10]  # single pass, identity fine
    assert state.artifacts["face_identity"][0] == {
        "box": list(BOX), "similarity": 0.9, "attempts": 0
    }


async def test_gate_retries_lower_creativity_and_keeps_best(monkeypatch):
    provider = _GateGen()
    state = await _run(provider, monkeypatch, [0.40, 0.80])  # drift, then recover
    assert provider.creativities == [0.10, 0.05]  # retried at halved creativity
    rec = state.artifacts["face_identity"][0]
    assert rec["attempts"] == 1 and rec["similarity"] == 0.8


async def test_gate_keeps_first_when_retry_is_worse(monkeypatch):
    provider = _GateGen()
    state = await _run(provider, monkeypatch, [0.45, 0.30])  # retry worse -> keep first
    assert provider.creativities == [0.10, 0.05]
    rec = state.artifacts["face_identity"][0]
    assert rec["attempts"] == 1 and rec["similarity"] == 0.45


async def test_gate_noop_when_no_face(monkeypatch):
    provider = _GateGen()
    state = await _run(provider, monkeypatch, [None])  # can't measure
    assert provider.creativities == [0.10]  # no retry
    assert state.artifacts["face_identity"][0] == {
        "box": list(BOX), "similarity": None, "attempts": 0
    }
