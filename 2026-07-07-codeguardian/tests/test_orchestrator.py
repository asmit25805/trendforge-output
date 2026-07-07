import uuid
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.core.orchestrator import Orchestrator, FatalError, TransientError
from src.core.models import ScanTask, TaskStatus, User, Project, Vulnerability, CVEReport

@pytest.fixture
def dummy_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password="hashed",
        role="user",
    )

@pytest.fixture
def dummy_project(dummy_user: User) -> Project:
    return Project(
        id=uuid.uuid4(),
        name="demo",
        repo_url="https://github.com/example/demo",
        owner_id=dummy_user.id,
    )

@pytest.fixture
def dummy_task(dummy_project: Project) -> ScanTask:
    return ScanTask(
        id=uuid.uuid4(),
        project_id=dummy_project.id,
        agent_name="test-agent",
        payload={"key": "value"},
    )

@pytest.mark.asyncio
async def test_successful_task_execution(dummy_task: ScanTask):
    orchestrator = Orchestrator("sqlite+aiosqlite:///:memory:")
    # Patch the internal TaskRunner to avoid real DB work
    with patch("src.core.orchestrator.TaskRunner.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = None
        await orchestrator.submit_task(dummy_task)
        # Allow background task to run
        await asyncio.sleep(0.2)
        status = await orchestrator.get_task_status(dummy_task.id)
        assert status == TaskStatus.SUCCESS

@pytest.mark.asyncio
async def test_fatal_error_marks_task_failed(dummy_task: ScanTask):
    orchestrator = Orchestrator("sqlite+aiosqlite:///:memory:")
    with patch("src.core.orchestrator.TaskRunner.run", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = FatalError("irrecoverable")
        await orchestrator.submit_task(dummy_task)
        await asyncio.sleep(0.2)
        status = await orchestrator.get_task_status(dummy_task.id)
        assert status == TaskStatus.FAILED

@pytest.mark.asyncio
async def test_transient_error_retries_task(dummy_task: ScanTask):
    orchestrator = Orchestrator("sqlite+aiosqlite:///:memory:")
    call_count = 0

    async def flaky_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise TransientError("temporary issue")
        return None

    with patch("src.core.orchestrator.TaskRunner.run", new=flaky_run):
        await orchestrator.submit_task(dummy_task)
        await asyncio.sleep(0.5)
        status = await orchestrator.get_task_status(dummy_task.id)
        assert status == TaskStatus.SUCCESS
        assert call_count == 2
