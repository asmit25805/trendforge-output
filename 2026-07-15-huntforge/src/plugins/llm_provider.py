import abc
import json
from typing import Any, List

import httpx
from loguru import logger
from pydantic import BaseSettings, Field, validator

from src.core.models import LLMResponse, Message


class LLMProviderPlugin(abc.ABC):
    """Abstract base for any LLM service exposing an OpenAI‑compatible API."""

    @abc.abstractmethod
    async def chat(self, messages: List[Message]) -> LLMResponse:
        """Send a list of messages to the LLM and return the response.

        Implementations must perform an HTTP request to the provider's chat endpoint
        and return a :class:`LLMResponse` instance.
        """
        raise NotImplementedError


class OpenAICompatAdapter(LLMProviderPlugin):
    """A minimal adapter that talks to an OpenAI‑compatible endpoint.

    The adapter expects an ``api_key`` and an optional ``base_url``.  It uses
    ``httpx`` with HTTP/2 support for efficiency.
    """

    class Settings(BaseSettings):
        api_key: str = Field(..., env="LLM_API_KEY")
        base_url: str = Field(default="https://api.openai.com/v1")

        @validator("api_key")
        def _non_empty(cls, v: str) -> str:
            if not v:
                raise ValueError("API key must not be empty")
            return v

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or self.Settings()
        self.client = httpx.AsyncClient(http2=True)

    async def chat(self, messages: List[Message]) -> LLMResponse:
        url = f"{self.settings.base_url}/chat/completions"
        payload = {
            "model": "gpt-4",
            "messages": [msg.dict() for msg in messages],
        }
        headers = {"Authorization": f"Bearer {self.settings.api_key}"}
        logger.debug("Sending chat request to %s", url)
        response = await self.client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return LLMResponse(**data)
