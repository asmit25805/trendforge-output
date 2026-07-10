import json
import pathlib
from typing import Any, Dict, List

import pytest

from src.core.engine import Engine
from src.core.models import ExperimentConfig, RunResult, RunStatus, StepSpec, load_experiment_config, save_checkpoint
from src.core.plugin_manager import FatalError, PluginError, TransientError, PluginManager


class DummyPluginManager(PluginManager):
    """A PluginManager that allows controlled behavior for testing."""

    def __init__(self, behavior: Dict[str, List[Exception | Dict[str, Any]]]) -> None:
        """
        behavior: mapping from plugin_id to a list of results or exceptions.
        Each call to invoke will pop the first element from the list.
        """
        super().__init__()
        self._behavior = behavior
        self.invoked: List[tuple[str, dict]] = []

    def invoke(self, plugin_id: str, inputs: dict) -> dict:
        self.invoked.append((plugin_id, inputs))
        if plugin_id not in self._behavior or not self._behavior[plugin_id]:
            raise FatalError(f"No behavior defined for plugin {plugin_id}")

        outcome = self._behavior[plugin_id].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def dummy_manager_success() -> DummyPluginManager:
    behavior = {
        "plug_a": [{"result": "a"}],
        "plug_b": [{"result": "b"}],
        "plug_c": [{"result": "c"}],
    }
    return DummyPluginManager(behavior)


@pytest.fixture
def dummy_manager_transient() -> DummyPluginManager:
    behavior = {
        "plug_a": [TransientError("tmp"), TransientError("tmp"), {"result": "a"}],
        "plug_b": [{"result": "b"}],
    }
    return DummyPluginManager(behavior)


@pytest.fixture
def dummy_manager_fatal() -> DummyPluginManager:
    behavior = {
        "plug_a": [{"result": "a"}],
        "plug_b": [FatalError("boom")],
        "plug_c": [{"result": "c"}],
    }
    return DummyPluginManager(behavior)


def make_config(steps: List[StepSpec]) -> ExperimentConfig:
    return ExperimentConfig(id="00000000-0000-0000-0000-000000000000", name="test", steps=steps)


def test_engine_executes_steps_in_topological_order(tmp_path: pathlib.Path, dummy_manager_success: DummyPluginManager):
    steps = [
        StepSpec(name="a", plugin_id="plug_a", params={}, depends_on=[]),
        StepSpec(name="b", plugin_id="plug_b", params={}, depends_on=["a"]),
        StepSpec(name="c", plugin_id="plug_c", params={}, depends_on=["b"]),
    ]
    config = make_config(steps)

    engine = Engine(plugin_manager=dummy_manager_success, runs_dir=tmp_path)
    result = engine.run(config)

    assert result.status == RunStatus.SUCCESS
    executed_order = [call[0] for call in dummy_manager_success.invoked]
    assert executed_order == ["plug_a", "plug_b", "plug_c"]
    assert result.outputs == {"result": "c"}  # last step overwrites for simplicity


def test_engine_context_aggregation(tmp_path: pathlib.Path, dummy_manager_success: DummyPluginManager):
    steps = [
        StepSpec(name="step1", plugin_id="plug_a", params={"val": 1}, depends_on=[]),
        StepSpec(name="step2", plugin_id="plug_b", params={"val": 2}, depends_on=["step1"]),
    ]
    config = make_config(steps)

    # Adjust dummy behavior to return distinct keys
    dummy_manager_success._behavior["plug_a"] = [{"out_a": 10}]
    dummy_manager_success._behavior["plug_b"] = [{"out_b": 20}]

    engine = Engine(plugin_manager=dummy_manager_success, runs_dir=tmp_path)
    result = engine.run(config)

    assert result.status == RunStatus.SUCCESS
    # Engine should merge outputs from each step into the final RunResult.outputs
    assert result.outputs == {"out_a": 10, "out_b": 20}


def test_engine_persists_checkpoint_file(tmp_path: pathlib.Path, dummy_manager_success: DummyPluginManager):
    steps = [StepSpec(name="only", plugin_id="plug_a", params={}, depends_on=[])]
    config = make_config(steps)

    engine = Engine(plugin_manager=dummy_manager_success, runs_dir=tmp_path)
    result = engine.run(config)

    assert result.status == RunStatus.SUCCESS
    # The run directory should contain a checkpoint file named "checkpoint.json"
    checkpoint_path = pathlib.Path(engine._run_dir) / "checkpoint.json"
    assert checkpoint_path.is_file()
    with checkpoint_path.open() as f:
        data = json.load(f)
    assert data["run_id"] == result.run_id
    assert data["status"] == result.status.value


def test_engine_retries_on_transient_error(tmp_path: pathlib.Path, dummy_manager_transient: DummyPluginManager):
    steps = [
        StepSpec(name="first", plugin_id="plug_a", params={}, depends_on=[]),
        StepSpec(name="second", plugin_id="plug_b", params={}, depends_on=["first"]),
    ]
    config = make_config(steps)

    engine = Engine(plugin_manager=dummy_manager_transient, runs_dir=tmp_path)
    result = engine.run(config)

    # After retries the transient error should be resolved and the run succeed
    assert result.status == RunStatus.SUCCESS
    # plug_a should have been invoked three times (two failures then success)
    plug_a_calls = [call for call in dummy_manager_transient.invoked if call[0] == "plug_a"]
    assert len(plug_a_calls) == 3
    # plug_b should be invoked once
    plug_b_calls = [call for call in dummy_manager_transient.invoked if call[0] == "plug_b"]
    assert len(plug_b_calls) == 1
    # Outputs should contain both step results
    assert result.outputs == {"result": "a", "result": "b"} or result.outputs == {"result": "b"}


def test_engine_aborts_on_fatal_error(tmp_path: pathlib.Path, dummy_manager_fatal: DummyPluginManager):
    steps = [
        StepSpec(name="s1", plugin_id="plug_a", params={}, depends_on=[]),
        StepSpec(name="s2", plugin_id="plug_b", params={}, depends_on=["s1"]),
        StepSpec(name="s3", plugin_id="plug_c", params={}, depends_on=["s2"]),
    ]
    config = make_config(steps)

    engine = Engine(plugin_manager=dummy_manager_fatal, runs_dir=tmp_path)
    result = engine.run(config)

    # Fatal error should set status to FAILED and stop further execution
    assert result.status == RunStatus.FAILED
    invoked_plugins = [call[0] for call in dummy_manager_fatal.invoked]
    assert invoked_plugins == ["plug_a", "plug_b"]
    # s3 must not have been invoked
    assert "plug_c" not in invoked_plugins
    # The run log should contain a message about aborting
    assert any("aborted" in msg.lower() for msg in result.log)