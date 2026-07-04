from __future__ import annotations

import json
import os
import re
import sys
import pathlib
import logging
from typing import List, Optional, Tuple, Dict, Any

import httpx
import openai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .models import Message, MemoryEntry, ToolResult, ReflectResult

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages sessions and provides a deterministic system prompt prefix."""

    _SYSTEM_PREFIX = "You are a helpful assistant."

    def get_system_prefix(self) -> str:
        """Return a deterministic system‑prompt prefix.

        The value is deliberately static so that repeated calls produce the same
        byte‑stable string, which is useful for caching.
        """
        return self._SYSTEM_PREFIX

    def create_session(self) -> "Session":
        """Factory method to create a new isolated Session."""
        return Session(self)


class Session:
    """Represents an isolated conversation session.

    It holds a list of :class:`Message` objects, interacts with the ``ToolEngine``
    and the ``UnifiedReflector`` and stores reflections in the ``MemoryStore``.
    """

    def __init__(self, manager: SessionManager):
        self.manager = manager
        self.messages: List[Message] = []
        self.memory_store = None  # Placeholder – can be injected by the user
        self.tool_engine = None   # Placeholder – can be injected by the user
        self.reflector = None     # Placeholder – can be injected by the user
        logger.debug("Session initialised with manager %s", manager)

    def add_message(self, message: Message) -> None:
        """Add a new message to the session history."""
        self.messages.append(message)
        logger.debug("Added message: %s", message)

    def run(self) -> Message:
        """Run the session: invoke tools, reflect, and return the assistant reply.

        This is a very small stub implementation that simply echoes the last
        user message prefixed with the system prompt. Real implementations would
        call the OpenAI API, run tools, and store reflections.
        """
        if not self.messages:
            raise ValueError("No messages in session to process")
        last_user_msg = self.messages[-1]
        response_content = f"{self.manager.get_system_prefix()} {last_user_msg.content}"
        response = Message(role="assistant", content=response_content)
        self.add_message(response)
        logger.debug("Session run produced response: %s", response)
        return response
