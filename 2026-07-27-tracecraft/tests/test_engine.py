import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
from unittest.mock import Mock, call

from src.core.engine import AgentLoop, LLMUnavailable
from src.core.models import ActionResult, SkillSpec, TraceRecord


class DummyActionResult:
    """Simple stand‑in for :class:`ActionResult` used in tests."""

    def __init__(self, stdout: str = "", stderr: str = "", exit_code: int = 0, error: str | None = None):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.error = error

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, DummyActionResult):
            return NotImplemented
        return (
            self.stdout == other.stdout
            and self.stderr == other.stderr
            and self.exit_code == other.exit_code
            and self.error == other.error
        )


@pytest.fixture
def dummy_skill() -> SkillSpec:
    """Create a minimal :class:`SkillSpec` with a render_prompt method."""
    spec = SkillSpec(
        name="test-skill",
        version="1.0.0",
        description="A dummy skill for testing",
        system_prompt="You are a helpful assistant.",
        parameters={},
    )
    # The real SkillSpec is expected to have a ``render_prompt`` method.
    # Attach a simple implementation that interpolates the task.
    def render_prompt(task: str = "") -> str:
        return f"{spec.system_prompt}\nTask: {task}"
    spec.render_prompt = render_prompt  # type: ignore[attr-defined]
    return spec


def test_agentloop_successful_run(tmp_path: Path, dummy_skill: SkillSpec) -> None:
    """AgentLoop should return a fully populated TraceRecord on success."""
    # Mock LLM output – must contain an ``action`` dict.
    llm_output = {"action": {"cmd": ["echo", "hello"]}}
    # Mock execution – return a successful ActionResult.
    exec_result = DummyActionResult(stdout="hello\n", exit_code=0)

    loop = AgentLoop(skill_spec=dummy_skill, docker_client=Mock())
    loop._call_llm = Mock(return_value=llm_output)
    loop._execute_action = Mock(return_value=exec_result)

    record = loop.run(task="say hello", skill="test-skill", skill_version="1.0.0")

    assert isinstance(record, TraceRecord)
    assert record.task == "say hello"
    assert record.skill == dummy_skill.name
    assert record.skill_version == dummy_skill.version
    assert len(record.steps) == 4  # think, act, prove, grow
    # Verify that the act and prove phases received the same action.
    act_step = record.steps[1]
    prove_step = record.steps[2]
    assert act_step["phase"] == "act"
    assert prove_step["phase"] == "prove"
    assert act_step["action"] == llm_output["action"]
    assert prove_step["action"] == llm_output["action"]
    # Ensure the artifact directory was created.
    assert record.artifact_dir.is_dir()


def test_agentloop_llm_retry_on_transient_error(tmp_path: Path, dummy_skill: SkillSpec) -> None:
    """AgentLoop should retry the LLM call on transient OpenAIError failures."""
    # First two calls raise OpenAIError, third succeeds.
    error = Exception("Transient LLM failure")
    llm_output = {"action": {"cmd": ["true"]}}
    exec_result = DummyActionResult(stdout="", exit_code=0)

    loop = AgentLoop(skill_spec=dummy_skill, docker_client=Mock(), max_retries=3)
    loop._call_llm = Mock(side_effect=[error, error, llm_output])
    loop._execute_action = Mock(return_value=exec_result)

    record = loop.run(task="noop", skill="test-skill", skill_version="1.0.0")

    # Verify that _call_llm was invoked three times.
    assert loop._call_llm.call_count == 3
    # The run should still succeed and produce a TraceRecord.
    assert isinstance(record, TraceRecord)
    assert record.steps[0]["phase"] == "think"
    assert record.steps[0]["llm_output"] == llm_output


def test_agentloop_llm_failure_raises_LLMUnavailable(tmp_path: Path, dummy_skill: SkillSpec) -> None:
    """If all retries fail, AgentLoop must raise LLMUnavailable."""
    error = Exception("Permanent LLM failure")
    loop = AgentLoop(skill_spec=dummy_skill, docker_client=Mock(), max_retries=2)
    loop._call_llm = Mock(side_effect=error)

    with pytest.raises(LLMUnavailable):
        loop.run(task="fail", skill="test-skill", skill_version="1.0.0")

    # Ensure the retry logic was exercised the expected number of times.
    assert loop._call_llm.call_count == 2


def test_agentloop_action_execution_error(tmp_path: Path, dummy_skill: SkillSpec) -> None:
    """When the ACT phase returns an error, PROVE should still run and the trace stays valid."""
    llm_output = {"action": {"cmd": ["false"]}}
    # Simulate a failing action (non‑zero exit code) for the ACT phase.
    act_result = DummyActionResult(stdout="", stderr="error", exit_code=1, error="Non‑zero exit")
    # PROVE phase returns a successful result.
    prove_result = DummyActionResult(stdout="", exit_code=0)

    loop = AgentLoop(skill_spec=dummy_skill, docker_client=Mock())
    loop._call_llm = Mock(return_value=llm_output)

    # Use a side_effect list to return different results for successive calls.
    loop._execute_action = Mock(side_effect=[act_result, prove_result])

    record = loop.run(task="run failing command", skill="test-skill", skill_version="1.0.0")

    act_step = record.steps[1]
    prove_step = record.steps[2]
    assert act_step["result"] == act_result
    assert prove_step["result"] == prove_result
    # The proof validity flag should be False because results differ.
    assert not prove_step.get("valid", True)


def test_agentloop_invalid_llm_output_missing_action(tmp_path: Path, dummy_skill: SkillSpec) -> None:
    """If the LLM output lacks an ``action`` key, AgentLoop should raise ValueError."""
    llm_output = {"thought": "I don't know what to do"}  # No ``action`` field.
    loop = AgentLoop(skill_spec=dummy_skill, docker_client=Mock())
    loop._call_llm = Mock(return_value=llm_output)

    with pytest.raises(ValueError, match="LLM output must contain an 'action' dict"):
        loop.run(task="invalid", skill="test-skill", skill_version="1.0.0")


def test_agentloop_trace_record_structure(tmp_path: Path, dummy_skill: SkillSpec) -> None:
    """TraceRecord must contain a UUID, correct metadata, and a deterministic steps layout."""
    llm_output = {"action": {"cmd": ["echo", "uuid"]}}
    exec_result = DummyActionResult(stdout="uuid\n", exit_code=0)

    loop = AgentLoop(skill_spec=dummy_skill, docker_client=Mock())
    loop._call_llm = Mock(return_value=llm_output)
    loop._execute_action = Mock(return_value=exec_result)

    record = loop.run(task="generate uuid", skill="test-skill", skill_version="1.0.0")

    # Verify UUID format.
    uuid_obj = uuid.UUID(record.run_id)
    assert isinstance(uuid_obj, uuid.UUID)

    # Verify metadata fields.
    assert record.task == "generate uuid"
    assert record.skill == dummy_skill.name
    assert record.skill_version == dummy_skill.version

    # Verify steps order and presence of required keys.
    expected_phases = ["think", "act", "prove", "grow"]
    actual_phases = [step["phase"] for step in record.steps]
    assert actual_phases == expected_phases

    for step in record.steps:
        assert "timestamp" in step
        # ``llm_output`` may be None for non‑think phases.
        assert "llm_output" in step
        # ``action`` may be None for the think phase.
        assert "action" in step
        # ``result`` may be None for the think phase.
        assert "result" in step
```