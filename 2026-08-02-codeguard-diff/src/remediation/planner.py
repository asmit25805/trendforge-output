import os
import json
import uuid
import time
import subprocess
from datetime import datetime
from typing import List, Literal

import requests
from rich.console import Console

from src.core.models import Finding, RuntimeConfig

_console = Console()

# Allowed status transitions for remediation actions
_RemediationStatus = Literal["pending", "applied", "failed"]


class RemediationAction:
    """Simple data holder for a remediation step.

    In a real implementation this would likely be a Pydantic model, but for the
    purposes of the tests a lightweight class is sufficient.
    """

    def __init__(self, finding: Finding, command: List[str]):
        self.id = uuid.uuid4()
        self.finding = finding
        self.command = command
        self.status: _RemediationStatus = "pending"
        self.created_at = datetime.utcnow()
        self.attempted_at: datetime | None = None
        self.finished_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "finding_id": str(self.finding.id),
            "command": self.command,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "attempted_at": self.attempted_at.isoformat() if self.attempted_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


def _load_api(endpoint: str, payload: dict) -> dict:
    """Call a remote remediation API.

    The function performs a POST request to ``endpoint`` with ``payload`` as JSON
    and returns the parsed JSON response. Errors raise a ``RuntimeError`` with a
    helpful message.
    """
    try:
        resp = requests.post(endpoint, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to call remediation API: {exc}") from exc


def apply_remediation(action: RemediationAction, runtime_cfg: RuntimeConfig) -> None:
    """Execute a remediation action.

    The function runs the command stored in ``action.command`` using ``subprocess``.
    It updates the ``status`` field based on the exit code.
    """
    action.attempted_at = datetime.utcnow()
    try:
        result = subprocess.run(action.command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            action.status = "applied"
        else:
            action.status = "failed"
            _console.print(
                f"Remediation command failed (exit {result.returncode}): {result.stderr}",
                style="bold red",
            )
    except Exception as exc:
        action.status = "failed"
        _console.print(f"Exception while applying remediation: {exc}", style="bold red")
    finally:
        action.finished_at = datetime.utcnow()
