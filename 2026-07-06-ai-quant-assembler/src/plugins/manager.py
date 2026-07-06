import importlib
import importlib.metadata
import logging
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Type

import polars as pl

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class DataProviderPlugin(ABC):
    """Abstract base class for data‑provider plugins.

    Each plugin must implement :meth:`fetch` which returns a ``MarketDataSlice``.
    """

    @abstractmethod
    def fetch(self, symbol: str, start: datetime, end: datetime) -> "MarketDataSlice":
        raise NotImplementedError


@dataclass
class PluginInfo:
    name: str
    entry_point: str
    plugin_cls: Type[DataProviderPlugin]


class PluginRegistry:
    """Registry that discovers and loads data‑provider plugins via entry‑points.

    The registry is thread‑safe and caches loaded plugin classes.
    """

    _plugins: Dict[str, PluginInfo]
    _lock: threading.Lock

    def __init__(self) -> None:
        self._plugins = {}
        self._lock = threading.Lock()
        self._discover_plugins()

    def _discover_plugins(self) -> None:
        """Populate the registry from ``ai_quant_assembler.plugins`` entry‑points."""
        for ep in importlib.metadata.entry_points().select(group="ai_quant_assembler.plugins"):
            try:
                plugin_cls = ep.load()
                if not issubclass(plugin_cls, DataProviderPlugin):
                    logger.warning("Entry point %s does not implement DataProviderPlugin", ep.name)
                    continue
                info = PluginInfo(name=ep.name, entry_point=ep.value, plugin_cls=plugin_cls)
                self._plugins[ep.name] = info
                logger.debug("Registered plugin %s", ep.name)
            except Exception as exc:
                logger.error("Failed to load plugin %s: %s", ep.name, exc)

    def get(self, name: str) -> DataProviderPlugin:
        """Return an instantiated plugin by name.

        Raises:
            KeyError: If the plugin name is unknown.
        """
        with self._lock:
            info = self._plugins[name]
        return info.plugin_cls()

    def list_plugins(self) -> List[str]:
        """Return a list of registered plugin names."""
        return list(self._plugins.keys())


# Backwards‑compatible alias used by the test suite
PluginManager = PluginRegistry
