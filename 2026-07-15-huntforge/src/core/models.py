import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator

# ---------------------------------------------------------------------------
# Core data models
# ---------------------------------------------------------------------------

class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class LLMResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(datetime.utcnow().timestamp()))
    model: str
    choices: List[Dict[str, Any]]

class Target(BaseModel):
    hostname: str
    port: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None

class Finding(BaseModel):
    type: str
    description: str
    severity: Literal["low", "medium", "high", "critical"] = "low"
    data: Optional[Dict[str, Any]] = None

class ExploitArtifact(BaseModel):
    name: str
    content: str
    language: Optional[str] = None

class Verdict(BaseModel):
    success: bool
    details: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class HuntConfig(BaseModel):
    target: Target
    recon: Dict[str, Any]
    exploit: Dict[str, Any]
    report: Optional[Dict[str, Any]] = None

class HuntEvent(BaseModel):
    event_type: str
    payload: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class HuntReport(BaseModel):
    target: Target
    findings: List[Finding]
    exploits: List[ExploitArtifact]
    verdicts: List[Verdict]
    generated_at: datetime = Field(default_factory=datetime.utcnow)

class ReportBundle(BaseModel):
    report: HuntReport
    signature: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
