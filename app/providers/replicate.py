import asyncio
import base64
import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.providers.base import AIProvider

API = "https://api.replicate.com/v1"
logger = logging.getLogger(__name__)

# Pinned versions (SPEC.md: Initial Models — never use floating versions)
MODELS = {
    "generative-upscaler": "philz1337x/clarity-upscaler:dfad41707589d68ecdccd1dfa600d55a208f9310748e44bfe35b4a6291453d5e",
    "captioner": "lucataco/florence-2-large:da53547e17d45b9cfb48174b2f18af8b83ca020fa76db62136bf9c6616762595",
    "deterministic-upscaler": "nightmareai/real-esrgan:b3ef194191d13140337468c916c2c5b96dd0cb06dffc032a022a31807f6a5ea8",
}


class ReplicateProvider(AIProvider):
    def __init__(self, token: str | None = None):
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token or settings.replicate_api_token}"},
            timeout=httpx.Timeout(120, read=120),
        )

    async def run(self, model: str, input: dict[str, Any]) -> Any:
        version = MODELS[model].split(":", 1)[1]
        pred = await self._create_with_retry(version, input)
        # A prediction that never settles would poll forever, holding one of
        # the few job slots and stalling the queue for every user. Failing the
        # job frees the slot and refunds the credits.
        deadline = time.monotonic() + settings.prediction_timeout_seconds
        while pred["status"] in ("starting", "processing"):
            if time.monotonic() >= deadline:
                await self._cancel(pred["id"])
                raise RuntimeError(
                    f"prediction {pred['id']} still {pred['status']} after "
                    f"{settings.prediction_timeout_seconds}s — gave up"
                )
            await asyncio.sleep(3)
            r = await self._client.get(f"{API}/predictions/{pred['id']}")
            pred = r.json()
        if pred["status"] != "succeeded":
            raise RuntimeError(f"prediction {pred['id']} {pred['status']}: {pred.get('error')}")
        return pred

    async def _cancel(self, prediction_id: str) -> None:
        """Stop paying for a run whose result we'll never use. Best effort:
        the timeout is the real outcome, a failed cancel must not mask it."""
        try:
            await self._client.post(f"{API}/predictions/{prediction_id}/cancel")
        except httpx.HTTPError:
            logger.warning("couldn't cancel timed-out prediction %s", prediction_id)

    async def _create_with_retry(self, version: str, input: dict[str, Any]) -> dict:
        for attempt in range(5):
            r = await self._client.post(
                f"{API}/predictions",
                json={"version": version, "input": input},
                headers={"Prefer": "wait"},
            )
            if r.status_code != 429:
                break
            await asyncio.sleep(2**attempt)
        r.raise_for_status()
        return r.json()

    async def upload(self, data: bytes, filename: str) -> str:
        if len(data) <= 256_000:
            mime = "image/png" if filename.endswith(".png") else "image/jpeg"
            return f"data:{mime};base64,{base64.b64encode(data).decode()}"
        r = await self._client.post(f"{API}/files", files={"content": (filename, data)})
        r.raise_for_status()
        return r.json()["urls"]["get"]

    async def download(self, url: str) -> bytes:
        r = await self._client.get(url)
        r.raise_for_status()
        return r.content
