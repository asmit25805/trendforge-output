from __future__ import annotations

import asyncio
import datetime
import json
import logging
import traceback
from collections import defaultdict
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, Type, Union
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.core.models import ScanTask, TaskStatus, Vulnerability, CVEReport, Project, User

logger = logging.getLogger(__name__)


class FatalError(Exception):
    """Raised when a task cannot be retried and must be marked as failed."""


class TransientError(Exception):
    """Raised when a task failed due to a temporary condition and should be retried."""


class TaskRunner:
    """Executes a single ScanTask using the appropriate agent implementation."""

    def __init__(self, task: ScanTask, session: AsyncSession):
        self.task = task
        self.session = session

    async def run(self) -> None:
        try:
            logger.info("Running task %s with agent %s", self.task.id, self.task.agent_name)
            # In a real implementation we would dynamically import the agent module.
            # For this simplified version we just simulate work.
            await asyncio.sleep(0.1)
            # Simulate a vulnerability discovery
            vuln = Vulnerability(
                scan_task_id=self.task.id,
                severity="low",
                description="Example vulnerability discovered by %s" % self.task.agent_name,
            )
            self.session.add(vuln)
            self.task.status = TaskStatus.SUCCESS
            self.task.finished_at = datetime.datetime.utcnow()
        except Exception as exc:
            logger.exception("Task %s failed", self.task.id)
            raise FatalError(str(exc))


class Orchestrator:
    """Coordinates the lifecycle of ScanTasks across agents and persists results."""

    def __init__(self, engine_url: str):
        self.engine = create_async_engine(engine_url, echo=False)
        self._task_runners: Dict[UUID, TaskRunner] = {}

    async def submit_task(self, task: ScanTask) -> None:
        async with AsyncSession(self.engine) as session:
            session.add(task)
            await session.commit()
            runner = TaskRunner(task, session)
            self._task_runners[task.id] = runner
            asyncio.create_task(self._execute_runner(runner))

    async def _execute_runner(self, runner: TaskRunner) -> None:
        try:
            await runner.run()
        except FatalError:
            # Mark task as failed in DB
            async with AsyncSession(self.engine) as session:
                stmt = update(ScanTask).where(ScanTask.id == runner.task.id).values(status=TaskStatus.FAILED)
                await session.execute(stmt)
                await session.commit()
        except TransientError:
            # Simple retry logic – re‑queue after a short delay
            await asyncio.sleep(1)
            await self._execute_runner(runner)

    async def get_task_status(self, task_id: UUID) -> Optional[TaskStatus]:
        async with AsyncSession(self.engine) as session:
            result = await session.execute(select(ScanTask.status).where(ScanTask.id == task_id))
            row = result.first()
            return row[0] if row else None
