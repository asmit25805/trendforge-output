from __future__ import annotations

import uuid
import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, validator


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    READ_ONLY = "read_only"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class User(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    email: EmailStr
    hashed_password: str
    role: UserRole = UserRole.USER
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

    @validator("hashed_password")
    def password_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("hashed_password must not be empty")
        return v


class Project(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    repo_url: str
    owner_id: uuid.UUID
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class ScanTask(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    agent_name: str
    payload: dict = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    started_at: Optional[datetime.datetime] = None
    finished_at: Optional[datetime.datetime] = None


class Vulnerability(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scan_task_id: uuid.UUID
    severity: Severity
    description: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    cve_id: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class CVEReport(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    generated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    vulnerabilities: List[Vulnerability]
    signature: Optional[str] = None
