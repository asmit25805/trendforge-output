from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional, Set

from pydantic import BaseModel, Field, validator

__all__ = [
    "TokenRecord",
    "AggregatedReport",
    "BudgetConfig",
    "AlertMessage",
    "CIContext",
]


class TokenRecord(BaseModel):
    """A normalised representation of a single token usage event."""

    provider: str = Field(..., description="Name of the LLM provider, e.g., 'openai'.")
    model: str = Field(..., description="Model identifier, e.g., 'gpt-4'.")
    prompt_tokens: int = Field(..., ge=0, description="Number of tokens in the prompt.")
    completion_tokens: int = Field(..., ge=0, description="Number of tokens in the completion.")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="When the record was generated.")

    @validator("provider", "model")
    def non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("must be a non‑empty string")
        return v

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def json_dict(self) -> dict:
        return json.loads(self.json())


class AggregatedReport(BaseModel):
    """Summary of token usage for a CI run, optionally per provider/model."""

    provider: str
    model: str
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    start_time: datetime
    end_time: datetime

    @validator("total_prompt_tokens", "total_completion_tokens", "total_tokens")
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("token counts must be non‑negative")
        return v

    @validator("end_time")
    def after_start(cls, v: datetime, values: dict) -> datetime:
        if "start_time" in values and v < values["start_time"]:
            raise ValueError("end_time must be after start_time")
        return v


class BudgetConfig(BaseModel):
    """Configuration for token budgeting per provider/model."""

    provider: str
    model: Optional[str] = None
    hard_limit_tokens: int = Field(..., gt=0, description="Hard token limit – exceeding this fails the CI run.")
    soft_limit_tokens: Optional[int] = Field(None, gt=0, description="Soft token limit – triggers a warning but does not fail.")

    @validator("soft_limit_tokens")
    def soft_not_exceed_hard(cls, v: Optional[int], values: dict) -> Optional[int]:
        hard = values.get("hard_limit_tokens")
        if v is not None and hard is not None and v > hard:
            raise ValueError("soft_limit_tokens cannot exceed hard_limit_tokens")
        return v


class AlertMessage(BaseModel):
    """Message payload sent to an alert back‑end."""

    title: str
    body: str
    severity: str = Field("info", description="Severity level, e.g., 'info', 'warning', 'error'.")

    @validator("severity")
    def allowed_severity(cls, v: str) -> str:
        allowed = {"info", "warning", "error", "critical"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return v


class CIContext(BaseModel):
    """Contextual information about the CI environment in which the library runs."""

    env: Mapping[str, str] = Field(default_factory=dict, description="Environment variables relevant to the CI run.")
    run_id: str = Field(..., description="Unique identifier for the CI run.")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
