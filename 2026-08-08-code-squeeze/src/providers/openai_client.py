import logging
from dataclasses import dataclass
from typing import List

from src.core.models import Config, Segment

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Simple container for the response returned by an LLM client."""

    content: str


class BaseLLMClient:
    """Abstract base class for LLM provider clients.

    Concrete implementations must provide an ``async generate`` method that accepts a
    list of ``Segment`` objects and returns an ``LLMResponse``.
    """

    def __init__(self, config: Config):
        self.config = config

    async def generate(self, segments: List[Segment]) -> LLMResponse:
        """Generate a response from the LLM.

        Sub‑classes should override this method.  The default implementation raises
        ``NotImplementedError`` to make the contract explicit.
        """
        raise NotImplementedError("BaseLLMClient.generate must be overridden by a subclass")


class DummyLLMClient(BaseLLMClient):
    """Fallback client used in tests and when no real provider is configured.

    It simply concatenates the ``content`` of each segment and returns it unchanged.
    """

    async def generate(self, segments: List[Segment]) -> LLMResponse:
        combined = "\n".join(seg.content for seg in segments)
        return LLMResponse(content=combined)


def get_client(config: Config) -> BaseLLMClient:
    """Factory that returns an appropriate LLM client based on ``config.provider``.

    For the purposes of this repository the ``dummy`` provider is used as a safe
    default.  Real implementations would import and instantiate the provider‑specific
    client (e.g., OpenAI, Azure, Ollama).
    """
    if config.provider.lower() == "dummy":
        return DummyLLMClient(config)
    # Default to dummy client for any unknown provider to keep the package functional.
    logger.warning("Unknown LLM provider '%s'; falling back to DummyLLMClient", config.provider)
    return DummyLLMClient(config)
