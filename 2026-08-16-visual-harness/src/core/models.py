'''"""Core data models and exception hierarchy for visual-harness.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class AutomationError(Exception):
    """Base exception for all automation related errors."""

    pass


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class UIElement:
    """Represents a UI element discovered via OCR.

    Attributes
    ----------
    identifier: str
        Unique identifier for the element.
    bounds: tuple[int, int, int, int]
        The (x, y, width, height) of the element on the screen.
    text: str
        The OCR‑extracted text for the element.
    """

    identifier: str
    bounds: tuple[int, int, int, int]
    text: str = ""


@dataclass
class CaptureFrame:
    """A captured screenshot.

    Attributes
    ----------
    image_path: Path
        Path to the image file.
    timestamp: float
        Time when the capture was taken.
    """

    image_path: Path
    timestamp: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict[str, Any]:
        return {"image_path": str(self.image_path), "timestamp": self.timestamp}


@dataclass
class AutomationCommand:
    """High‑level command that the engine will translate into concrete actions.

    Attributes
    ----------
    action: str
        The type of action, e.g. ``"click"``.
    target: str
        Identifier or text of the UI element the action targets.
    args: dict
        Additional arguments for the action.
    """

    action: str
    target: str
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    """Configuration and state for a single automation run.

    The session is loaded from a JSON configuration file.  Tests use a helper
    ``Session.load_f`` which historically pointed to ``load_from_path``; the
    alias is retained for backward compatibility.
    """

    config: Dict[str, Any]

    @classmethod
    def load_from_path(cls, path: Path) -> "Session":
        """Load a JSON configuration file and return a :class:`Session`.

        Parameters
        ----------
        path: Path
            Path to a JSON file containing the session configuration.
        """
        with path.open() as f:
            data = json.load(f)
        return cls(config=data)

    # Compatibility alias used in older tests
    load_f = load_from_path


# ---------------------------------------------------------------------------
# Re‑export plugin helpers for convenience (used throughout the code base)
# ---------------------------------------------------------------------------

from src.plugins import (  # noqa: E402
    register_plugin,
    get_plugin,
    load_plugin,
    discover_config,
)
'''