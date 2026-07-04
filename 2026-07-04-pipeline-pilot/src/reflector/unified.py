from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, List, Sequence

import openai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.core.models import Message, MemoryEntry, ReflectResult

logger = logging.getLogger(__name__)


def _default_reflection_prompt() -> str:
    """Return the default system prompt used for reflection.

    The prompt asks the model to summarise key insights from the conversation
    without introducing hallucinations.
    """
    return (
        "You are a reflective assistant. Extract concise, factual insights "
        "from the following conversation. Return each insight as a separate line."
    )


class UnifiedReflector:
    """Generates reflections from a sequence of :class:`Message` objects.

    The implementation is deliberately simple: it concatenates the messages,
    sends them to the OpenAI API with the default reflection prompt, and parses
    the newline‑separated response into a :class:`ReflectResult`.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        if not self.api_key:
            raise ValueError("OpenAI API key must be provided via argument or OPENAI_API_KEY env var")
        logger.debug("UnifiedReflector initialised with model %s", model)

    @retry(
        retry=retry_if_exception_type(openai.RateLimitError),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(5),
    )
    def reflect(self, messages: Sequence[Message]) -> ReflectResult:
        """Run the reflection chain and return a :class:`ReflectResult`."""
        prompt = _default_reflection_prompt()
        conversation = "\n".join(f"{m.role}: {m.content}" for m in messages)
        response = openai.ChatCompletion.create(
            model=self.model,
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": conversation}],
            api_key=self.api_key,
        )
        raw = response.choices[0].message.content.strip()
        reflections = [line.strip() for line in raw.splitlines() if line.strip()]
        logger.info("Reflection produced %d insights", len(reflections))
        return ReflectResult(reflections=reflections)
