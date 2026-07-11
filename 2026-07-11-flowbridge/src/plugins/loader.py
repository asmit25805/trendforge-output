from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Protocol

from flowbridge.core.models import ProviderSpec

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol defining the interface a provider plugin must implement
# ---------------------------------------------------------------------------

class ProviderPlugin(Protocol):
    """Minimal protocol that a provider plugin must satisfy.

    The concrete plugin class is expected to expose a ``spec`` attribute of type
    :class:`ProviderSpec` and a ``perform`` callable that executes an action.
    """

    spec: ProviderSpec

    def perform(self, action_id: str, params: Dict[str, Any]) -> Any:
        ...

# ---------------------------------------------------------------------------
# Plugin loader implementation
# ---------------------------------------------------------------------------

@dataclass
class PluginLoader:
    """Loads provider plugins from a directory.

    The loader scans a directory for ``*.py`` files, imports them as modules and
    registers any class that implements the :class:`ProviderPlugin` protocol.
    """

    plugins_path: Path
    loaded_plugins: Dict[str, ProviderPlugin] = field(default_factory=dict)

    def discover(self) -> None:
        """Discover and load all provider plugins under ``plugins_path``.
        """
        if not self.plugins_path.is_dir():
            logger.warning("Plugin directory %s does not exist", self.plugins_path)
            return
        for file in self.plugins_path.glob("*.py"):
            self._load_module(file)

    def _load_module(self, file_path: Path) -> None:
        module_name = file_path.stem
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            logger.error("Could not create spec for %s", file_path)
            return
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)  # type: ignore[arg-type]
        except Exception as exc:
            logger.exception("Failed to import plugin %s: %s", module_name, exc)
            return
        # Look for a class named ``Plugin`` that follows ProviderPlugin protocol
        plugin_cls = getattr(module, "Plugin", None)
        if plugin_cls is None:
            logger.debug("No Plugin class in %s", module_name)
            return
        plugin_instance = plugin_cls()
        if not hasattr(plugin_instance, "spec"):
            logger.error("Plugin %s does not expose a 'spec' attribute", module_name)
            return
        self.loaded_plugins[plugin_instance.spec.id] = plugin_instance
        logger.info("Loaded plugin %s (id=%s)", module_name, plugin_instance.spec.id)

    def get(self, provider_id: str) -> ProviderPlugin:
        """Retrieve a loaded plugin by its provider identifier.
        """
        try:
            return self.loaded_plugins[provider_id]
        except KeyError as exc:
            raise KeyError(f"Provider '{provider_id}' not found") from exc
