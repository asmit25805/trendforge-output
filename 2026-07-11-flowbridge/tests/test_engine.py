import json
import time
from pathlib import Path
from typing import List

import pytest
from sqlalchemy import select

from flowbridge.core.engine import PipelineEngine, run_pipeline, pipeline_status
from flowbridge.core.models import (
    ActionSpec,
    NodeSpec,
    PipelineSpec,
    ProviderSpec,
    RunState,
    RunStatus,
)

@pytest.fixture
def dummy_provider_spec() -> ProviderSpec:
    """A minimal ProviderSpec used for testing the engine."""
    return ProviderSpec(id="dummy_provider", name="Dummy Provider", config={})

@pytest.fixture
def simple_pipeline(dummy_provider_spec: ProviderSpec) -> PipelineSpec:
    """Create a tiny pipeline with two nodes that depend on each other."""
    node_a = NodeSpec(
        id="node_a",
        provider_id=dummy_provider_spec.id,
        action_id="action_a",
        downstream=["node_b"],
        params={"value": 1},
    )
    node_b = NodeSpec(
        id="node_b",
        provider_id=dummy_provider_spec.id,
        action_id="action_b",
        downstream=[],
        params={"value": 2},
    )
    return PipelineSpec(
        id="test_pipeline",
        description="A simple two‑node pipeline",
        trigger="manual",
        nodes=[node_a, node_b],
    )

def test_run_pipeline(simple_pipeline: PipelineSpec):
    """Validate that ``run_pipeline`` returns a successful ``RunStatus``."""
    status = run_pipeline(simple_pipeline)
    assert isinstance(status, RunStatus)
    assert status.pipeline_id == simple_pipeline.id
    assert status.state == RunState.SUCCESS
    assert status.started_at is not None
    assert status.finished_at is not None

def test_pipeline_status(simple_pipeline: PipelineSpec):
    """After running a pipeline, ``pipeline_status`` should retrieve the same record."""
    # Ensure a run exists
    run_pipeline(simple_pipeline)
    retrieved = pipeline_status(simple_pipeline.id)
    assert retrieved is not None
    assert retrieved.pipeline_id == simple_pipeline.id
    assert retrieved.state == RunState.SUCCESS
