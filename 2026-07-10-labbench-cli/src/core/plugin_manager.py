from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Mapping, Dict

import yaml
from pydantic import BaseModel, validator

from src.core.models import PluginSpec as BasePluginSpec  # type: ignore


class PluginError(RuntimeError):
    """Base class for plugin execution errors."""


class FatalError(PluginError):
    """Indicates a non‑recoverable plugin failure."""


class TransientError(PluginError):
    """Indicates a temporary failure that may be retried."""


class PluginSpec(BasePluginSpec):
    """Concrete plugin specification extending the base model."""

    @validator("entrypoint")
    def entrypoint_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("entrypoint must be a non‑empty string")
        return v


class PluginManager:
    """Manages discovery and execution of plugins."""

    def __init__(self, plugins: Mapping[str, PluginSpec] | None = None):
        self.plugins: Dict[str, PluginSpec] = dict(plugins or {})
        self.logger = logging.getLogger(__name__)

    def register(self, spec: PluginSpec) -> None:
        """Register a new plugin specification."""
        self.plugins[spec.id] = spec
        self.logger.debug("Registered plugin %s", spec.id)

    def get(self, plugin_id: str) -> PluginSpec:
        """Retrieve a plugin specification by its identifier."""
        try:
            return self.plugins[plugin_id]
        except KeyError as exc:
            raise FatalError(f"Plugin '{plugin_id}' not found") from exc

    def execute(self, plugin_id: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        """Execute the plugin and return its JSON output.

        Parameters
        ----------
        plugin_id: str
            Identifier of the plugin to run.
        params: Mapping[str, Any]
            Parameters passed to the plugin via stdin as JSON.
        """
        spec = self.get(plugin_id)
        cmd = spec.entrypoint.split()
        self.logger.info("Executing plugin %s with command %s", plugin_id, cmd)
        try:
            proc = subprocess.run(
                cmd,
                input=json.dumps(params).encode(),
                capture_output=True,
                check=False,
                timeout=300,
            )
        except Exception as exc:
            raise TransientError(f"Failed to start plugin '{plugin_id}': {exc}") from exc

        if proc.returncode != 0:
            raise FatalError(
                f"Plugin '{plugin_id}' exited with code {proc.returncode}: {proc.stderr.decode()}"
            )
        try:
            return json.loads(proc.stdout.decode())
        except json.JSONDecodeError as exc:
            raise FatalError(f"Plugin '{plugin_id}' produced invalid JSON output") from exc


__all__ = [
    "PluginError",
    "FatalError",
    "TransientError",
    "PluginSpec",
    "PluginManager",
]
