from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import jsonschema
from jsonschema import ValidationError

from src.core.models import CVEReport, Project, ScanTask, Severity, TaskStatus, Vulnerability

logger = logging.getLogger(__name__)


class LLMAgent:
    """Example LLM‑based reasoning agent.

    The agent receives a `ScanTask` payload, validates it against a JSON schema,
    performs a mock LLM call (simulated with asyncio.sleep), and returns a list
    of `Vulnerability` objects.
    """

    def __init__(self, schema_path: Path):
        self.schema = json.loads(schema_path.read_text())

    async def process(self, task: ScanTask) -> List[Vulnerability]:
        # Validate payload against schema
        try:
            jsonschema.validate(instance=task.payload, schema=self.schema)
        except ValidationError as exc:
            logger.error("Payload validation failed for task %s: %s", task.id, exc)
            raise

        # Simulate LLM processing delay
        await asyncio.sleep(0.2)

        # Produce a deterministic dummy vulnerability for demonstration
        vuln = Vulnerability(
            scan_task_id=task.id,
            severity=Severity.MEDIUM,
            description="Potential issue identified by LLM agent",
            file_path=task.payload.get("file_path"),
            line_number=task.payload.get("line_number"),
        )
        return [vuln]
