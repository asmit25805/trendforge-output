import json
import logging
import sqlite3
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import openai
import polars as pl
import re

from src.core.models import StrategySpec

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class LLMClient:
    """Thin wrapper around the OpenAI ChatCompletion API.

    The client is deliberately tiny – it only sends a prompt and returns the
    raw string response.  Errors are logged and re‑raised so that callers can
    decide how to handle them.
    """

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        response = openai.ChatCompletion.create(
            model=self.model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        )
        content = response.choices[0].message.content
        logger.debug("LLM response: %s", content)
        return content


class StrategyGenerator:
    """Generate a :class:`StrategySpec` from a natural‑language description.

    The generator uses :class:`LLMClient` to obtain a DSL expression and then
    wraps it in a :class:`StrategySpec` dataclass.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.llm = llm_client or LLMClient()

    def generate(self, prompt: str) -> StrategySpec:
        system_prompt = (
            "You are an expert quantitative analyst. Return a single line DSL "
            "expression that implements the strategy described by the user."
        )
        raw = self.llm.chat(system_prompt, prompt)
        # Very naive extraction – keep the first non‑empty line.
        expression = next((line.strip() for line in raw.splitlines() if line.strip()), "")
        if not expression:
            raise ValueError("LLM did not return a strategy expression")
        name = f"generated_{int(time.time())}"
        return StrategySpec(name=name, expression=expression)
