from __future__ import annotations

import importlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Tuple, Type, Union, cast

from src.core.models import AutomationError, Session

# --------------------------------------------------------------------------- #
# Plugin registry
# --------------------------------------------------------------------------- #

_PLUGIN_REGISTRY: Dict[str, Type[Any]] = {}

def register_plugin(name: str) -> Callable[[Type[Any]], Type[Any]]:
    """
    Decorator that registers a class as a plugin under *name*.
    The decorated class must accept a ``Session`` instance as its first
    argument.
    """
    def decorator(cls: Type[Any]) -> Type[Any]:
        if name in _PLUGIN_REGISTRY:
            raise AutomationError(f"Plugin name '{name}' already registered")
        _PLUGIN_REGISTRY[name] = cls
        return cls
    return decorator

def get_plugin(name: str) -> Type[Any]:
    """
    Return the plugin class registered under *name*.
    Raises ``AutomationError`` if the name is unknown.
    """
    try:
        return _PLUGIN_REGISTRY[name]
    except KeyError as exc:
        raise AutomationError(f"Plugin '{name}' not found") from exc

def load_plugin(name: str, session: Session) -> Any:
    """
    Instantiate the plugin identified by *name* using *session*.
    If the plugin is not yet registered, an attempt is made to import a
    module following the convention ``src.backends.<name>_backend`` or
    ``src.ocr.<name>_ocr``. The module is expected to call ``register_plugin``
    at import time.
    """
    if name not in _PLUGIN_REGISTRY:
        # Try to import a backend module first, then an OCR module.
        module_paths = [
            f"src.backends.{name}_backend",
            f"src.ocr.{name}_ocr",
        ]
        for module_path in module_paths:
            try:
                importlib.import_module(module_path)
                break
            except ModuleNotFoundError:
                continue
        else:
            raise AutomationError(f"Unable to locate plugin module for '{name}'")
    plugin_cls = get_plugin(name)
    return plugin_cls(session)

# --------------------------------------------------------------------------- #
# Configuration discovery
# --------------------------------------------------------------------------- #

def discover_config(
    start_dir: Path,
    max_depth: int = 10,
) -> Dict[str, Any]:
    """
    Walk upwards from *start_dir* looking for a ``.visual_harness.json`` file.
    The first file found is parsed and returned; an empty dict is returned if
    none is found or if parsing fails.
    """
    current = start_dir.resolve()
    for _ in range(max_depth):
        candidate = current / ".visual_harness.json"
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logging.getLogger("visual_harness.plugins").error(
                    "Failed to parse config %s: %s", candidate, exc
                )
                return {}
        if current.parent == current:
            break
        current = current.parent
    return {}

# --------------------------------------------------------------------------- #
# Plugin initialization helpers
# --------------------------------------------------------------------------- #

def initialize_backend(session: Session) -> Any:
    """
    Load and instantiate the backend plugin defined by ``session.backend_name``.
    Returns the backend instance ready for ``capture_window`` and injection
    methods.
    """
    if not session.backend_name:
        raise AutomationError("Backend name not configured in session")
    return load_plugin(session.backend_name, session)

def initialize_ocr_provider(session: Session) -> Any:
    """
    Load and instantiate the OCR provider plugin defined by
    ``session.ocr_provider_name``. Returns the OCR instance ready for
    ``recognize`` and ``detect_state`` calls.
    """
    if not session.ocr_provider_name:
        raise AutomationError("OCR provider name not configured in session")
    return load_plugin(session.ocr_provider_name, session)

def initialize_plugins(session: Session) -> Tuple[Any, Any]:
    """
    Convenience function that returns a tuple ``(backend, ocr_provider)``.
    Both components are instantiated using the session configuration.
    """
    backend = initialize_backend(session)
    ocr = initialize_ocr_provider(session)
    return backend, ocr

# --------------------------------------------------------------------------- #
# Retry utilities
# --------------------------------------------------------------------------- #

def exponential_backoff(attempt: int, base: float = 0.5, cap: float = 5.0) -> float:
    """
    Compute a back‑off delay for *attempt* (0‑based). The delay grows
    exponentially with *base* and is capped at *cap* seconds.
    """
    delay = base * (2 ** attempt)
    return min(delay, cap)

def retry_operation(
    func: Callable[..., Any],
    max_retries: int = 3,
    base_delay: float = 0.5,
) -> Any:
    """
    Execute *func* and retry on ``AutomationError`` up to *max_retries* times.
    Between attempts a delay computed by ``exponential_backoff`` is applied.
    If all attempts fail, the last exception is re‑raised.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return func()
        except AutomationError as exc:
            last_exc = exc
            delay = exponential_backoff(attempt, base=base_delay)
            logging.getLogger("visual_harness.plugins").warning(
                "Transient error on attempt %d: %s – retrying after %.2fs",
                attempt + 1,
                exc,
                delay,
            )
            time.sleep(delay)
    raise cast(AutomationError, last_exc) if last_exc else AutomationError(
        "Unknown error during retry operation"
    )

# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

__all__ = [
    "register_plugin",
    "get_plugin",
    "load_plugin",
    "discover_config",
    "initialize_backend",
    "initialize_ocr_provider",
    "initialize_plugins",
    "retry_operation",
]