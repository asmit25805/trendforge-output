from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import requests

from src.core.models import ActionResult, SkillSpec, TraceRecord
from src.skills.registry import SkillNotFound, SkillRegistry
from src.validation.trace import TraceValidator, validate_trace

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class LLMUnavailable(RuntimeError):
    """Raised when the language model service cannot be reached."""

    pass


class AgentLoop:
    """Core loop that executes a skill and validates the resulting trace.

    The loop is deliberately simple for the purpose of the test suite:
    * It looks up a skill in the provided ``SkillRegistry``.
    * It pretends to call an LLM (here we just simulate a delay).
    * It creates an ``ActionResult`` and a ``TraceRecord``.
    * It validates the trace using a ``TraceValidator``.
    """

    def __init__(self, registry: SkillRegistry, validator: TraceValidator) -> None:
        self.registry = registry
        self.validator = validator

    def run(self, name: str, version: str, inputs: Dict[str, Any]) -> TraceRecord:
        """Execute a skill and return a validated ``TraceRecord``.

        Parameters
        ----------
        name: str
            The skill name.
        version: str
            The semantic version of the skill.
        inputs: dict
            Arbitrary input data for the skill.
        """
        try:
            spec: SkillSpec = self.registry.get_skill(name, version)
        except SkillNotFound as exc:
            log.error("Skill not found: %s %s", name, version)
            raise exc

        # Simulate an LLM call – in real code this would be an HTTP request.
        time.sleep(0.01)

        # Create a dummy ActionResult – the real implementation would execute the skill.
        result = ActionResult(
            stdout=json.dumps({"skill": name, "version": version, "inputs": inputs}),
            stderr="",
            exit_code=0,
            timestamp=datetime.utcnow().isoformat(),
        )

        # Build the trace record.
        trace = TraceRecord(
            id=str(uuid.uuid4()),
            skill_name=name,
            skill_version=version,
            inputs=inputs,
            result=result,
            created_at=datetime.utcnow().isoformat(),
        )

        # Validate the trace – raise if validation fails.
        self.validator.validate(trace)
        return trace


def run_agent(registry: SkillRegistry, validator: TraceValidator, name: str, version: str, inputs: Dict[str, Any]) -> TraceRecord:
    """Convenience wrapper that creates an ``AgentLoop`` and runs a single skill.

    This function is used by the example script and the test suite.
    """
    loop = AgentLoop(registry, validator)
    return loop.run(name, version, inputs)
