import os
import pathlib
import json
from typing import List

import pytest
from unittest.mock import MagicMock, patch

from src.core.engine import SessionManager, Session
from src.core.models import Message, ToolResult, ReflectResult, MemoryEntry


def test_system_prefix_is_deterministic():
    manager = SessionManager()
    first = manager.get_system_prefix()
    second = manager.get_system_prefix()
    assert first == second, "System prefix should be deterministic across calls"


def test_session_run_returns_assistant_message():
    manager = SessionManager()
    session = Session(manager)
    user_msg = Message(role="user", content="Hello world")
    session.add_message(user_msg)
    response = session.run()
    assert isinstance(response, Message)
    assert response.role == "assistant"
    assert "Hello world" in response.content
