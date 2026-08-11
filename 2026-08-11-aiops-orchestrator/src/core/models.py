'''\
Core data models for aiops-orchestrator.
'''\

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Configure a module‑level logger
logger = logging.getLogger("aiops.core")


@dataclass
class Event:
    """Simple event container used throughout the system."""
    name: str
    payload: Dict[str, Any]


class EventBus:
    """In‑memory publish/subscribe bus.

    Handlers can subscribe to a named event and will be called with the
    :class:`Event` instance when that event is published.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[Event], None]]] = {}

    def subscribe(self, event_name: str, handler: Callable[[Event], None]) -> None:
        """Register *handler* for *event_name*.
        """
        self._subscribers.setdefault(event_name, []).append(handler)

    def publish(self, event: Event) -> None:
        """Publish *event* to all registered handlers.
        """
        for handler in self._subscribers.get(event.name, []):
            try:
                handler(event)
            except Exception as exc:
                logger.error("Error handling event %s: %s", event.name, exc)

# Placeholder dataclasses for future extensions (Config, PluginManifest, CronJob, etc.)
# They can be expanded as the project grows.
