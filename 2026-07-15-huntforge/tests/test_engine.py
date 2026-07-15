import asyncio
from typing import List

import pytest
import pytest_asyncio
from pydantic import BaseModel

from src.core.engine import Orchestrator, HuntConfig, run_hunt
from src.core.models import Finding, ExploitArtifact, Target, Verdict, HuntReport
from src.plugins.llm_provider import LLMProviderPlugin, OpenAICompatAdapter


class DummyFinding(Finding):
    """A deterministic finding used for testing."""

    type: str = "dummy"
    description: str = "A dummy finding for unit tests"
    severity: str = "low"
    data: dict = {}


class DummyLLMProvider(LLMProviderPlugin):
    async def chat(self, messages: List[Message]):  # type: ignore[name-defined]
        # Return a minimal LLMResponse without performing any network I/O.
        from src.core.models import LLMResponse
        return LLMResponse(id="dummy", object="chat.completion", created=0, model="test", choices=[])


@pytest_asyncio.fixture
async def orchestrator() -> Orchestrator:
    return Orchestrator(llm_provider=DummyLLMProvider())


@pytest.mark.asyncio
async def test_orchestrator_runs_without_error(orchestrator: Orchestrator):
    # Minimal configuration that exercises the orchestrator path.
    cfg = HuntConfig(
        target=Target(hostname="localhost"),
        recon={"modules": []},
        exploit={"modules": []},
    )
    bundle = await orchestrator.run_hunt(cfg)
    assert isinstance(bundle, ReportBundle)
    assert isinstance(bundle.report, HuntReport)
    # The report should contain no findings or exploits for the empty config.
    assert bundle.report.findings == []
    assert bundle.report.exploits == []
    assert all(v.success for v in bundle.report.verdicts)
