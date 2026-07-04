from __future__ import annotations

import json
import time
from typing import Any, List, Optional

from pydantic import BaseModel, Field, validator

# ---------------------------------------------------------------------------
# Core data models shared across the pipeline-pilot code base.
# ---------------------------------------------------------------------------


class Message(BaseModel):
    """A single chat message exchanged between user and assistant."""

    role: str = Field(..., description="One of 'system', 'user', or 'assistant'.")
    content: str = Field(..., description="The textual content of the message.")

    @validator("role")
    def _validate_role(cls, v: str) -> str:
        if v not in {"system", "user", "assistant"}:
            raise ValueError("role must be 'system', 'user', or 'assistant'")
        return v

    def dict(self, *args, **kwargs):  # type: ignore[override]
        """Return a plain‑dict representation compatible with JSON serialisation."""
        return {"role": self.role, "content": self.content}


class MemoryEntry(BaseModel):
    """A stored reflection or memory entry.

    The ``timestamp`` is stored as a Unix epoch float for easy sorting.
    """

    title: str = Field(..., description="Human‑readable title of the memory.")
    content: str = Field(..., description="Full text of the memory.")
    timestamp: float = Field(default_factory=time.time, description="Creation time as Unix epoch.")

    def dict(self, *args, **kwargs):  # type: ignore[override]
        return {"title": self.title, "content": self.content, "timestamp": self.timestamp}


class ToolResult(BaseModel):
    """Result returned by a tool execution."""

    tool_name: str = Field(..., description="Name of the tool that was run.")
    output: Any = Field(..., description="Arbitrary output produced by the tool.")
    success: bool = Field(default=True, description="Whether the tool ran without error.")

    def dict(self, *args, **kwargs):  # type: ignore[override]
        return {"tool_name": self.tool_name, "output": self.output, "success": self.success}


class ReflectResult(BaseModel):
    """Result of the reflection step.

    ``reflections`` is a list of extracted insights.
    """

    reflections: List[str] = Field(default_factory=list, description="List of reflection strings.")

    def dict(self, *args, **kwargs):  # type: ignore[override]
        return {"reflections": self.reflections}
