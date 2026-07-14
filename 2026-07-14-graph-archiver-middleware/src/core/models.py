from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class NodeStatus(str, Enum):
    """Lifecycle states of a FileNode."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


class ActionType(str, Enum):
    """Supported action types for a rule."""

    DOWNLOAD = "download"
    TRANSFORM = "transform"
    ARCHIVE = "archive"


class Action(BaseModel):
    """An action to be performed when a rule matches a FileNode."""

    type: ActionType
    params: Dict[str, Any] = Field(default_factory=dict)


class RetryPolicy(BaseModel):
    """Retry configuration for download operations."""

    max_retries: int = 3
    backoff_factor: float = 0.5
    retry_on: List[int] = Field(default_factory=lambda: [500, 502, 503, 504])


class FileNode(BaseModel):
    """Metadata representation of a file stored in the knowledge graph."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    path: Path
    size: int = 0
    checksum: Optional[str] = None
    status: NodeStatus = NodeStatus.QUEUED
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("path", mode="before")
    @classmethod
    def ensure_path(cls, v: Any) -> Path:
        return Path(v)

    def update_status(self, new_status: NodeStatus) -> None:
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)


class Rule(BaseModel):
    """A declarative rule that triggers actions based on a FileNode's metadata."""

    name: str
    condition: Any  # Callable[[FileNode], bool] – stored as a lambda in tests
    actions: List[Action]
    enabled: bool = True

    def matches(self, node: FileNode) -> bool:
        if not self.enabled:
            return False
        try:
            return self.condition(node)
        except Exception:
            return False
