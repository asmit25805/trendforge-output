from __future__ import annotations

import filecmp
import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

import docker
from docker.errors import DockerException, APIError

from src.core.models import ActionResult, BenchmarkScenario, BenchmarkResult, TraceRecord

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class TraceValidationError(RuntimeError):
    """Raised when a trace does not meet the expected validation criteria."""

    pass


@dataclass
class TraceValidator:
    """Validate a :class:`TraceRecord` against expected outcomes.

    The validator currently performs a very small set of checks suitable for the
    unit tests:
    * The ``exit_code`` must be ``0``.
    * The ``stdout`` must be valid JSON.
    * Optional file‑system diffs can be compared using ``filecmp``.
    """

    def validate(self, trace: TraceRecord) -> None:
        result: ActionResult = trace.result
        if result.exit_code != 0:
            raise TraceValidationError("Non‑zero exit code in trace")
        try:
            json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise TraceValidationError("stdout is not valid JSON") from exc
        # Additional validation (e.g., file diffs) could be added here.
        log.info("Trace %s validated successfully", trace.id)


def validate_trace(trace: TraceRecord) -> None:
    """Convenient function that validates a trace using the default validator.

    This helper mirrors the public API expected by ``src.core.engine``.
    """
    validator = TraceValidator()
    validator.validate(trace)
