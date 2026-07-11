"""Provider abstraction (SPEC.md: Model Providers).

The pipeline never knows which provider executed a model. Models are
referred to by logical name; each provider maps names to its own
implementation (and pinned version).
"""

from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    @abstractmethod
    async def run(self, model: str, input: dict[str, Any]) -> Any:
        """Run a model by logical name and return its raw output."""

    @abstractmethod
    async def upload(self, data: bytes, filename: str) -> str:
        """Upload a file, returning a URL the provider's models accept."""
