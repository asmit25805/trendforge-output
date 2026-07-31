import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, List

import pytest
import yaml

from src.core.engine import PromptEngine, run_optim, _load_config
from src.core.models import (
    ConfigurationError,
    EvaluationError,
    OptimizationConfig,
    PromptCandidate,
    TrialResult,
)
from src.plugins.registry import BaseLLMDriver, PluginRegistry


class DummyDriver(BaseLLMDriver):
    """A minimal driver used for testing that returns a deterministic prompt."""

    def name(self) -> str:
        return "dummy"

    def generate_prompt(self, trial_index: int) -> PromptCandidate:
        return PromptCandidate(prompt=f"test prompt {trial_index}")


@pytest.fixture(autouse=True)
def register_dummy_driver():
    registry = PluginRegistry.get_instance()
    # Ensure a clean state for each test run
    registry._drivers.clear()
    registry.register_driver(DummyDriver())
    yield
    registry._drivers.clear()


def test_load_config(tmp_path: Path):
    yaml_content = {
        "target_path": "my.module:function",
        "metrics": ["accuracy"],
        "driver": "dummy",
        "max_trials": 2,
    }
    config_file = tmp_path / "optimisation.yaml"
    config_file.write_text(yaml.safe_dump(yaml_content))

    cfg = _load_config(config_file)
    assert isinstance(cfg, OptimizationConfig)
    assert cfg.driver == "dummy"
    assert cfg.max_trials == 2


def test_engine_runs(tmp_path: Path):
    yaml_content = {
        "target_path": "my.module:function",
        "metrics": ["accuracy"],
        "driver": "dummy",
        "max_trials": 3,
    }
    config_file = tmp_path / "optimisation.yaml"
    config_file.write_text(yaml.safe_dump(yaml_content))

    # Run the engine via the public helper
    run_optim(config_file)

    # Verify that result files were created
    result_dir = Path("results")
    assert result_dir.is_dir()
    json_files = list(result_dir.glob("*.json"))
    assert len(json_files) == 3
    for jf in json_files:
        data = json.loads(jf.read_text())
        assert "candidate_id" in data
        assert "metrics" in data
        assert isinstance(data["metrics"], dict)
