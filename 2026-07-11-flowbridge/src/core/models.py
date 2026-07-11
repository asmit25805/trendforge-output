from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CredentialType(str, Enum):
    """Supported credential storage types."""

    API_KEY = "api_key"
    OAUTH = "oauth"
    USER_PASS = "user_pass"

class AuthType(str, Enum):
    """Authentication mechanisms used by providers."""

    BASIC = "basic"
    TOKEN = "token"
    NONE = "none"

class RunState(str, Enum):
    """Possible runtime states for a pipeline execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"

# ---------------------------------------------------------------------------
# Core data models
# ---------------------------------------------------------------------------

class ProviderSpec(BaseModel):
    """Specification of a provider plugin.

    Attributes
    ----------
    id: str
        Unique identifier for the provider.
    name: str
        Human‑readable name.
    config: Dict[str, Any]
        Provider‑specific configuration dictionary.
    """

    id: str
    name: str
    config: Dict[str, Any] = Field(default_factory=dict)

class ActionSpec(BaseModel):
    """Specification of an action that a provider can perform."""

    id: str
    name: str
    description: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)

class NodeSpec(BaseModel):
    """A node in a pipeline DAG.

    Attributes
    ----------
    id: str
        Unique node identifier.
    provider_id: str
        Identifier of the provider that will execute the action.
    action_id: str
        Identifier of the action to invoke.
    downstream: List[str]
        List of node ids that depend on this node's output.
    params: Dict[str, Any]
        Parameters passed to the action.
    """

    id: str
    provider_id: str
    action_id: str
    downstream: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)

class PipelineSpec(BaseModel):
    """Top‑level pipeline definition."""

    id: str
    description: Optional[str] = None
    trigger: str
    nodes: List[NodeSpec]

class Credential(BaseModel):
    """Stored credential used by providers at runtime."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: CredentialType
    auth_type: AuthType
    value: str
    expires_at: Optional[datetime] = None

    @validator("expires_at", pre=True, always=True)
    def set_default_expiry(cls, v):
        return v

class RunStatus(BaseModel):
    """Current status of a pipeline run."""

    pipeline_id: str
    state: RunState = RunState.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
