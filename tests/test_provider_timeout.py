import asyncio

import pytest

from app.core.config import settings
from app.providers import replicate
from app.providers.replicate import ReplicateProvider


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        pass


class FakeReplicate:
    """Answers with `statuses` in order, repeating the last one forever."""

    def __init__(self, *statuses: str):
        self.statuses = list(statuses)
        self.canceled: list[str] = []
        self.polls = 0

    def _next(self) -> dict:
        status = self.statuses[0] if len(self.statuses) == 1 else self.statuses.pop(0)
        return {"id": "pred_1", "status": status}

    async def post(self, url: str, **kwargs) -> FakeResponse:
        if url.endswith("/cancel"):
            self.canceled.append(url)
            return FakeResponse({})
        return FakeResponse(self._next())

    async def get(self, url: str) -> FakeResponse:
        self.polls += 1
        return FakeResponse(self._next())


def provider_with(fake: FakeReplicate) -> ReplicateProvider:
    p = ReplicateProvider(token="test")
    p._client = fake
    return p


@pytest.fixture
def instant_sleep(monkeypatch):
    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(replicate.asyncio, "sleep", no_sleep)


def test_prediction_that_never_settles_is_given_up_on(monkeypatch):
    """Polling forever holds one of the few job slots; the queue stalls for
    everyone. Failing frees the slot and refunds the user."""
    monkeypatch.setattr(settings, "prediction_timeout_seconds", 0)
    fake = FakeReplicate("processing")

    with pytest.raises(RuntimeError, match="gave up"):
        asyncio.run(provider_with(fake).run("captioner", {}))
    assert fake.canceled  # and we stop paying for the run


def test_timeout_survives_a_failed_cancel(monkeypatch):
    """The timeout is the real outcome — a cancel that doesn't go through must
    not turn it into something else."""
    import httpx

    monkeypatch.setattr(settings, "prediction_timeout_seconds", 0)
    fake = FakeReplicate("processing")
    create = fake.post

    async def refuse_to_cancel(url, **kwargs):
        if url.endswith("/cancel"):
            raise httpx.HTTPError("replicate down")
        return await create(url, **kwargs)

    fake.post = refuse_to_cancel
    with pytest.raises(RuntimeError, match="gave up"):
        asyncio.run(provider_with(fake).run("captioner", {}))


def test_a_normal_prediction_still_polls_to_completion(instant_sleep):
    fake = FakeReplicate("starting", "processing", "succeeded")
    pred = asyncio.run(provider_with(fake).run("captioner", {}))
    assert pred["status"] == "succeeded"
    assert fake.polls == 2 and not fake.canceled


def test_failed_prediction_still_raises(instant_sleep):
    fake = FakeReplicate("failed")
    with pytest.raises(RuntimeError, match="failed"):
        asyncio.run(provider_with(fake).run("captioner", {}))
    assert not fake.canceled  # nothing to cancel, it's already over
