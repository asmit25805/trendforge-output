from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, validator

from src.core.models import Project, ScanTask, TaskStatus, User, Vulnerability, CVEReport
from src.core.orchestrator import Orchestrator

router = APIRouter()
logger = logging.getLogger(__name__)

# Dependency placeholder – in a real app this would retrieve the current user
async def get_current_user() -> User:
    raise HTTPException(status_code=401, detail="Unauthorized")


class ProjectCreate(BaseModel):
    name: str
    repo_url: str

    @validator("repo_url")
    def must_be_url(cls, v: str) -> str:
        if not v.startswith("http://") and not v.startswith("https://"):
            raise ValueError("repo_url must be a valid URL")
        return v


@router.post("/projects", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, user: User = Depends(get_current_user)):
    project = Project(
        id=uuid.uuid4(),
        name=payload.name,
        repo_url=payload.repo_url,
        owner_id=user.id,
    )
    # Persist project – omitted for brevity
    return project


class ScanTaskCreate(BaseModel):
    project_id: uuid.UUID
    agent_name: str
    payload: Dict[str, Any] = Field(default_factory=dict)


@router.post("/tasks", response_model=ScanTask, status_code=status.HTTP_202_ACCEPTED)
async def submit_task(
    task: ScanTaskCreate,
    background: BackgroundTasks,
    orchestrator: Orchestrator = Depends(lambda: Orchestrator("postgresql+asyncpg://user:pass@localhost/db")),
):
    scan_task = ScanTask(
        id=uuid.uuid4(),
        project_id=task.project_id,
        agent_name=task.agent_name,
        payload=task.payload,
    )
    await orchestrator.submit_task(scan_task)
    return scan_task


@router.get("/tasks/{task_id}/status", response_model=TaskStatus)
async def get_task_status(task_id: uuid.UUID, orchestrator: Orchestrator = Depends()):
    status_ = await orchestrator.get_task_status(task_id)
    if status_ is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return status_


@router.get("/projects/{project_id}/report", response_model=CVEReport)
async def get_report(project_id: uuid.UUID):
    # In a real implementation we would query the DB for the latest report.
    raise HTTPException(status_code=501, detail="Report generation not implemented in this stub")


@router.get("/tasks/stream")
async def stream_tasks(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            # Placeholder payload – in a real system this would stream task updates.
            yield "data: {}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
