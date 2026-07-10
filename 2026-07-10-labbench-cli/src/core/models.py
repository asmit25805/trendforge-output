from __future__ import annotations

import json
import uuid
import yaml
import datetime
from pathlib import Path
from typing import Any, Mapping, Optional, List, Union

import networkx as nx
from pydantic import BaseModel, Field, validator
from enum import Enum


class StepSpec(BaseModel):
    """Specification of a single experiment step."""

    name: str
    plugin_id: str
    params: Mapping[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)

    @validator("name")
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("step name cannot be empty")
        return v


class ExperimentConfig(BaseModel):
    """Root model for an experiment definition."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    steps: List[StepSpec]

    @validator("steps")
    def unique_step_names(cls, v: List[StepSpec]) -> List[StepSpec]:
        names = [s.name for s in v]
        if len(set(names)) != len(names):
            raise ValueError("step names must be unique")
        return v


class PluginSpec(BaseModel):
    """Specification of a plugin executable."""

    id: str
    entrypoint: str  # command line to launch the plugin
    description: Optional[str] = None

    @validator("entrypoint")
    def entrypoint_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("entrypoint cannot be empty")
        return v


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class RunResult(BaseModel):
    """Result of a single step execution, persisted as a checkpoint."""

    experiment_id: uuid.UUID
    step_name: str
    status: RunStatus
    start_time: datetime.datetime
    end_time: datetime.datetime
    output: Optional[Mapping[str, Any]] = None
    error: Optional[str] = None


def load_experiment_config(path: Union[str, Path]) -> ExperimentConfig:
    """Load an experiment configuration from a YAML or JSON file.

    Parameters
    ----------
    path: Union[str, Path]
        Path to the configuration file.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Experiment config not found: {p}")
    with p.open() as f:
        if p.suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(f)
        else:
            data = json.load(f)
    return ExperimentConfig.parse_obj(data)


def save_checkpoint(result: RunResult, directory: Union[str, Path]) -> Path:
    """Persist a RunResult as JSON in the given directory.

    Returns the path of the written file.
    """
    dir_path = Path(directory)
    dir_path.mkdir(parents=True, exist_ok=True)
    filename = f"{result.experiment_id}_{result.step_name}.json"
    out_path = dir_path / filename
    with out_path.open("w") as f:
        json.dump(result.dict(), f, default=str, indent=2)
    return out_path


__all__ = [
    "StepSpec",
    "ExperimentConfig",
    "PluginSpec",
    "RunStatus",
    "RunResult",
    "load_experiment_config",
    "save_checkpoint",
]
