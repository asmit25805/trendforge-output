import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Callable, List

import pytest
from unittest.mock import MagicMock, patch

from src.core.engine import SkillEngine
from src.core.models import IllustrationRequest, QAReport, IllustrationResult
from src.memory import MemoryStore


@pytest.fixture
def temp_db_path() -> Path:
    """Create a temporary file for SQLite databases and clean up after tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield Path(path)
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def memory_store(temp_db_path: Path) -> MemoryStore:
    """Provide a fresh MemoryStore backed by a temporary SQLite file."""
    store = MemoryStore(db_path=str(temp_db_path))
    yield store
    # Ensure the connection is closed before file removal
    store._conn.close()


@pytest.fixture
def engine(memory_store: MemoryStore) -> SkillEngine:
    """Instantiate SkillEngine with a fresh MemoryStore."""
    eng = SkillEngine(memory=memory_store)
    # Ensure deterministic retry behavior for tests
    eng._runtime_config.max_retries = 3
    eng._runtime_config.retry_backoff_factor = 0.0
    return eng


def make_request() -> IllustrationRequest:
    """Create a minimal valid IllustrationRequest."""
    return IllustrationRequest(
        request_id="11111111-1111-1111-1111-111111111111",
        input_type="text",
        raw_content="示例文本",
        target_use="slide",
        custom_accent=None,
    )


def test_engine_successful_flow(engine: SkillEngine) -> None:
    """Engine should produce a valid IllustrationResult on a happy path."""
    request = make_request()

    # Mock PromptBuilder to return a deterministic prompt
    engine._prompt_builder.build_prompt = MagicMock(return_value="prompt for chart")
    engine._prompt_builder.validate_prompt = MagicMock(return_value=True)

    # Mock image generation to return dummy bytes
    engine._image_client.generate_image = MagicMock(return_value=b"\x89PNG\r\n\x1a\n")

    # Mock validator to return a passing QAReport
    engine._validator.run_checks = MagicMock(
        return_value=QAReport(passed=True, failed_checks=[], details={}, retryable=False)
    )

    result = engine.run(request)

    assert isinstance(result, IllustrationResult)
    assert result.request_id == request.request_id
    assert result.image_bytes.startswith(b"\x89PNG")
    assert result.prompt_used == "prompt for chart"
    assert result.qa_report.passed is True
    # Ensure persistence was called
    stored = engine._memory.get_result(request.request_id)
    assert stored is not None
    assert stored["request_id"] == request.request_id


def test_engine_retries_on_transient_error(engine: SkillEngine) -> None:
    """Transient network errors should be retried up to max_retries."""
    request = make_request()
    engine._prompt_builder.build_prompt = MagicMock(return_value="prompt")
    engine._prompt_builder.validate_prompt = MagicMock(return_value=True)

    # First two calls raise a transient error, third succeeds
    side_effects: List[Exception | bytes] = [
        RuntimeError("Transient failure 1"),
        RuntimeError("Transient failure 2"),
        b"\x89PNG\r\n\x1a\n",
    ]

    def generate_image(*_, **__) -> bytes:
        result = side_effects.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    engine._image_client.generate_image = MagicMock(side_effect=generate_image)
    engine._validator.run_checks = MagicMock(
        return_value=QAReport(passed=True, failed_checks=[], details={}, retryable=False)
    )

    result = engine.run(request)

    assert isinstance(result, IllustrationResult)
    assert result.image_bytes.startswith(b"\x89PNG")
    # Verify that generate_image was called three times
    assert engine._image_client.generate_image.call_count == 3


def test_engine_fatal_error_missing_api_key(engine: SkillEngine) -> None:
    """Missing required configuration should raise a fatal error."""
    request = make_request()
    engine._prompt_builder.build_prompt = MagicMock(return_value="prompt")
    engine._prompt_builder.validate_prompt = MagicMock(return_value=True)

    # Simulate missing API key causing a fatal error in the image client
    engine._image_client.generate_image = MagicMock(
        side_effect=RuntimeError("Missing IMAGE_MODEL_API_KEY")
    )

    with pytest.raises(RuntimeError) as excinfo:
        engine.run(request)

    assert "Missing IMAGE_MODEL_API_KEY" in str(excinfo.value)


def test_engine_validation_retryable(engine: SkillEngine) -> None:
    """When validator marks a result retryable, engine should regenerate once."""
    request = make_request()
    engine._prompt_builder.build_prompt = MagicMock(return_value="prompt")
    engine._prompt_builder.validate_prompt = MagicMock(return_value=True)

    # First generation returns a retryable failure, second succeeds
    first_report = QAReport(
        passed=False,
        failed_checks=["layout"],
        details={"reason": "misaligned"},
        retryable=True,
    )
    second_report = QAReport(passed=True, failed_checks=[], details={}, retryable=False)

    engine._image_client.generate_image = MagicMock(return_value=b"\x89PNG\r\n\x1a\n")
    engine._validator.run_checks = MagicMock(side_effect=[first_report, second_report])

    result = engine.run(request)

    assert isinstance(result, IllustrationResult)
    assert result.qa_report.passed is True
    # Ensure two validation runs occurred (original + retry)
    assert engine._validator.run_checks.call_count == 2


def test_engine_persistence_of_intermediate_state(engine: SkillEngine) -> None:
    """Engine should persist intermediate artifacts for auditability."""
    request = make_request()
    engine._prompt_builder.build_prompt = MagicMock(return_value="prompt")
    engine._prompt_builder.validate_prompt = MagicMock(return_value=True)
    engine._image_client.generate_image = MagicMock(return_value=b"\x89PNG\r\n\x1a\n")
    engine._validator.run_checks = MagicMock(
        return_value=QAReport(passed=True, failed_checks=[], details={}, retryable=False)
    )

    engine.run(request)

    # Verify request row exists
    cur = engine._memory._conn.execute(
        "SELECT payload FROM requests WHERE request_id = ?", (request.request_id,)
    )
    row = cur.fetchone()
    assert row is not None
    payload = json.loads(row["payload"])
    assert payload["request_id"] == request.request_id

    # Verify intermediate stage was recorded
    cur = engine._memory._conn.execute(
        "SELECT data FROM intermediate WHERE request_id = ? AND stage = ?",
        (request.request_id, "prompt"),
    )
    row = cur.fetchone()
    assert row is not None
    assert "prompt" in row["data"]


def test_engine_hook_emission(engine: SkillEngine) -> None:
    """Registered hooks should be invoked with the correct payload."""
    request = make_request()
    engine._prompt_builder.build_prompt = MagicMock(return_value="prompt")
    engine._prompt_builder.validate_prompt = MagicMock(return_value=True)
    engine._image_client.generate_image = MagicMock(return_value=b"\x89PNG\r\n\x1a\n")
    engine._validator.run_checks = MagicMock(
        return_value=QAReport(passed=True, failed_checks=[], details={}, retryable=False)
    )

    captured: List[dict] = []

    def hook(payload: dict) -> None:
        captured.append(payload)

    engine.register_hook("engine_completed", hook)

    engine.run(request)

    assert any(p.get("request_id") == request.request_id for p in captured)
    assert any(p.get("status") == "completed" for p in captured)