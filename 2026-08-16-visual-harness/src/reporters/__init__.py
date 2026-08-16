from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Protocol, Type, Union, cast

from src.core.models import AutomationError, Session
from src.plugins import discover_config, get_plugin, load_plugin, register_plugin

# --------------------------------------------------------------------------- #
# Reporter plugin registry
# --------------------------------------------------------------------------- #

_REPORTER_REGISTRY: Dict[str, Type["BaseReporter"]] = {}

def register_reporter(name: str) -> Callable[[Type["BaseReporter"]], Type["BaseReporter"]]:
    """
    Decorator that registers a concrete reporter class under *name*.
    The class must inherit from :class:`BaseReporter` and accept a
    :class:`Session` instance as its first constructor argument.
    """
    def decorator(cls: Type["BaseReporter"]) -> Type["BaseReporter"]:
        if name in _REPORTER_REGISTRY:
            raise AutomationError(f"Reporter name '{name}' already registered")
        _REPORTER_REGISTRY[name] = cls
        return cls
    return decorator

def get_reporter_class(name: str) -> Type["BaseReporter"]:
    """
    Return the reporter class registered under *name*.
    Raises :class:`AutomationError` if the name is unknown.
    """
    try:
        return _REPORTER_REGISTRY[name]
    except KeyError as exc:
        raise AutomationError(f"Reporter '{name}' not found") from exc

def load_reporter(name: str, session: Session) -> "BaseReporter":
    """
    Instantiate the reporter identified by *name* using *session*.
    If the reporter is not yet registered, an attempt is made to import a
    module following the convention ``src.reporters.<name>_reporter``.
    The imported module is expected to call ``register_reporter`` at import time.
    """
    if name not in _REPORTER_REGISTRY:
        module_path = f"src.reporters.{name}_reporter"
        try:
            __import__(module_path)
        except ModuleNotFoundError as exc:
            raise AutomationError(f"Unable to locate reporter module for '{name}'") from exc
    reporter_cls = get_reporter_class(name)
    return reporter_cls(session)

# --------------------------------------------------------------------------- #
# Core reporter protocol
# --------------------------------------------------------------------------- #

class BaseReporter(Protocol):
    """
    Minimal protocol that all reporters must satisfy.
    Implementations receive a :class:`Session` at construction time and
    provide a :meth:`generate` method that returns a string representation
    of the supplied data.
    """
    def __init__(self, session: Session) -> None: ...

    def generate(self, data: Dict[str, Any]) -> str: ...

# --------------------------------------------------------------------------- #
# Built‑in reporters
# --------------------------------------------------------------------------- #

@register_reporter("json")
class JsonReporter:
    """
    Serialises the supplied data to a pretty‑printed JSON string.
    """
    def __init__(self, session: Session) -> None:
        self.session = session
        self.logger = logging.getLogger("visual_harness.reporters.json")
        self.logger.debug("JsonReporter initialised with session %s", session)

    def generate(self, data: Dict[str, Any]) -> str:
        """
        Return a JSON string with an indentation of two spaces.
        Non‑serialisable objects are converted to their ``repr``.
        """
        def default(o: Any) -> Any:
            try:
                return o.__dict__
            except Exception:
                return repr(o)

        json_str = json.dumps(data, indent=2, default=default, ensure_ascii=False)
        self.logger.debug("Generated JSON report of length %d", len(json_str))
        return json_str

@register_reporter("text")
class TextReporter:
    """
    Produces a human‑readable plain‑text report.
    """
    def __init__(self, session: Session) -> None:
        self.session = session
        self.logger = logging.getLogger("visual_harness.reporters.text")
        self.logger.debug("TextReporter initialised with session %s", session)

    def generate(self, data: Dict[str, Any]) -> str:
        """
        Return a multi‑line string where each top‑level key is rendered as a
        header followed by its JSON‑serialised value.
        """
        lines: List[str] = []
        for key, value in data.items():
            header = f"=== {key.upper()} ==="
            lines.append(header)
            try:
                body = json.dumps(value, indent=2, ensure_ascii=False)
            except TypeError:
                body = repr(value)
            lines.append(body)
            lines.append("")  # blank line between sections
        report = "\n".join(lines).strip()
        self.logger.debug("Generated text report with %d sections", len(data))
        return report

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #

def _resolve_output_path(session: Session, path: Union[str, Path, None]) -> Path:
    """
    Resolve *path* relative to the session's debug directory.
    If *path* is ``None``, a default file ``report.txt`` inside the debug
    directory is used.
    """
    base_dir = Path(session.debug_dir) if getattr(session, "debug_dir", None) else Path.cwd()
    if path is None:
        return base_dir / "report.txt"
    p = Path(path)
    return p if p.is_absolute() else base_dir / p

def _load_default_reporter_name(session: Session) -> str:
    """
    Determine the default reporter name from configuration files.
    The function walks up from the current working directory looking for a
    ``.visual_harness.json`` file. If the file contains a ``default_reporter``
    key, its value is returned; otherwise ``json`` is used.
    """
    config = discover_config(Path.cwd())
    name = cast(str, config.get("default_reporter", "json"))
    return name

# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def generate_report(
    session: Session,
    data: Dict[str, Any],
    reporter_name: str | None = None,
) -> str:
    """
    Generate a report string using the selected reporter.
    If *reporter_name* is ``None``, the default reporter defined in the
    configuration hierarchy is used.
    """
    if reporter_name is None:
        reporter_name = _load_default_reporter_name(session)
    reporter = load_reporter(reporter_name, session)
    return reporter.generate(data)

def write_report(
    session: Session,
    data: Dict[str, Any],
    output_path: Union[str, Path, None] = None,
    reporter_name: str | None = None,
) -> Path:
    """
    Generate a report and write it to *output_path*.
    The function returns the absolute :class:`Path` of the written file.
    """
    report_str = generate_report(session, data, reporter_name)
    target_path = _resolve_output_path(session, output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("w", encoding="utf-8") as f:
        f.write(report_str)
    logger = logging.getLogger("visual_harness.reporters")
    logger.info("Report written to %s using reporter %s", target_path, reporter_name or "default")
    return target_path

def report_and_exit(
    session: Session,
    data: Dict[str, Any],
    exit_code: int = 0,
    output_path: Union[str, Path, None] = None,
    reporter_name: str | None = None,
) -> None:
    """
    Convenience wrapper for CLI entry points.
    Generates a report, writes it, prints the path to stdout and exits the
    process with *exit_code*.
    """
    path = write_report(session, data, output_path, reporter_name)
    print(f"Report generated: {path}", file=sys.stdout)
    sys.exit(exit_code)

# --------------------------------------------------------------------------- #
# Exported symbols
# --------------------------------------------------------------------------- #

__all__ = [
    "register_reporter",
    "get_reporter_class",
    "load_reporter",
    "generate_report",
    "write_report",
    "report_and_exit",
    "BaseReporter",
]