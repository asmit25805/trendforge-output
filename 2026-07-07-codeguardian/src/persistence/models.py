from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

# Enums must match those defined in src.core.models
from src.core.models import UserRole, Severity, TaskStatus


class User(Base):
    __tablename__ = "users"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.USER)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    projects = relationship("Project", back_populates="owner")


class Project(Base):
    __tablename__ = "projects"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    repo_url = Column(String, nullable=False)
    owner_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="projects")
    scan_tasks = relationship("ScanTask", back_populates="project")


class ScanTask(Base):
    __tablename__ = "scan_tasks"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    agent_name = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    status = Column(SAEnum(TaskStatus), nullable=False, default=TaskStatus.PENDING)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="scan_tasks")
    vulnerabilities = relationship("Vulnerability", back_populates="scan_task")


class Vulnerability(Base):
    __tablename__ = "vulnerabilities"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_task_id = Column(PGUUID(as_uuid=True), ForeignKey("scan_tasks.id"), nullable=False)
    severity = Column(SAEnum(Severity), nullable=False)
    description = Column(Text, nullable=False)
    file_path = Column(String, nullable=True)
    line_number = Column(Integer, nullable=True)
    cve_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    scan_task = relationship("ScanTask", back_populates="vulnerabilities")


class CVEReport(Base):
    __tablename__ = "cve_reports"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    generated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    vulnerabilities = Column(JSONB, nullable=False)  # Stored as list of dicts
    signature = Column(String, nullable=True)

    project = relationship("Project")
