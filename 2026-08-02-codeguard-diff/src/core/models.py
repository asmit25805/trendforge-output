'''Core data models for codeguard-diff.

All public classes are Pydantic ``BaseModel`` subclasses providing validation,
serialization, and convenient constructors. They are imported throughout the
project to guarantee a single source of truth for field definitions and types.
'''

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, validator


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class FilePatch(BaseModel):
    file_path: Path
    added_lines: List[int]
    removed_lines: List[int]
    diff: str

    @validator('diff')
    def diff_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('diff cannot be empty')
        return v


class Finding(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    file_path: Path
    line: int
    severity: Severity
    title: str
    description: str
    status: FindingStatus = FindingStatus.OPEN
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ScanResult(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    patches: List[FilePatch]
    findings: List[Finding]
    runtime_config: RuntimeConfig


class RuntimeConfig(BaseModel):
    use_apparmor: bool = False
    use_landlock: bool = False
    use_seccomp: bool = False
    additional_env: Optional[dict] = None

    @validator('additional_env', pre=True, always=True)
    def set_default_env(cls, v):
        return v or {}
