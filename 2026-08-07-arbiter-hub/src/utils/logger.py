from __future__ import annotations

import sys
import asyncio
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Union

from loguru import logger as _loguru_logger
from pydantic import BaseSettings, Field, validator


class LoggerSettings(BaseSettings):
    """
    Configuration for the central logger.

    Attributes
    ----------
    level: str
        Minimum severity level to emit (e.g. "DEBUG", "INFO").
    format: str
        Log message format understood by ``loguru``.
    log_file: Optional[str]
        Path to a file for persistent logs; if ``None`` only console output is used.
    rotation: str
        Size or time based rotation rule (e.g. "10 MB", "1 day").
    retention: str
        Retention policy for old log files (e.g. "7 days").
    """

    level: str = Field(
        "INFO",
        description="Minimum severity level to emit",
    )
    format: str = Field(
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {message}",
        description="Log message format",
    )
    log_file: Optional[str] = Field(
        None,
        description="Optional file path for persistent logs",
    )
    rotation: str = Field(
        "10 MB",
        description="Log rotation size or interval",
    )
    retention: str = Field(
        "7 days",
        description="Retention period for rotated logs",
    )

    @validator("level")
    def _validate_level(cls, v: str) -> str:
        allowed = {
            "TRACE",
            "DEBUG",
            "INFO",
            "SUCCESS",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"Invalid log level: {v}")
        return upper


def _configure_logger(settings: LoggerSettings) -> None:
    """
    Apply the supplied settings to the global ``loguru`` logger.

    All previous sinks are removed before new ones are added to avoid duplicate
    output when the module is reloaded during tests.
    """
    _loguru_logger.remove()
    _loguru_logger.add(
        sys.stderr,
        level=settings.level,
        format=settings.format,
        enqueue=True,
        colorize=True,
    )
    if settings.log_file:
        _loguru_logger.add(
            settings.log_file,
            level=settings.level,
            format=settings.format,
            rotation=settings.rotation,
            retention=settings.retention,
            enqueue=True,
        )


# Initialise the logger at import time using default settings.
_default_settings = LoggerSettings()
_configure_logger(_default_settings)


class AsyncLogger:
    """
    Thin async wrapper around the ``loguru`` logger.

    The wrapper mirrors the most common logging methods but returns ``awaitable``
    objects so that callers can ``await logger.debug(...)`` without blocking the
    event loop. Internally the calls are delegated to the synchronous ``loguru``
    implementation because ``loguru`` is thread‑safe and uses a background queue
    when ``enqueue=True``.
    """

    def __init__(self, base_logger: Any = _loguru_logger) -> None:
        self._base = base_logger

    async def trace(self, message: str, **kwargs: Any) -> None:
        """Log a trace‑level message."""
        self._base.trace(message, **kwargs)

    async def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug‑level message."""
        self._base.debug(message, **kwargs)

    async def info(self, message: str, **kwargs: Any) -> None:
        """Log an info‑level message."""
        self._base.info(message, **kwargs)

    async def success(self, message: str, **kwargs: Any) -> None:
        """Log a success‑level message."""
        self._base.success(message, **kwargs)

    async def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning‑level message."""
        self._base.warning(message, **kwargs)

    async def error(self, message: str, **kwargs: Any) -> None:
        """Log an error‑level message."""
        self._base.error(message, **kwargs)

    async def critical(self, message: str, **kwargs: Any) -> None:
        """Log a critical‑level message."""
        self._base.critical(message, **kwargs)

    async def exception(self, message: str, **kwargs: Any) -> None:
        """
        Log an exception with traceback information.

        The ``exception`` method should be called from an ``except`` block.
        """
        self._base.exception(message, **kwargs)


# Export a singleton that the rest of the codebase can import.
logger = _loguru_logger
async_logger = AsyncLogger()


def reload_logger(settings: Optional[LoggerSettings] = None) -> None:
    """
    Re‑apply logger configuration.

    Parameters
    ----------
    settings: Optional[LoggerSettings]
        If provided, the new settings replace the current configuration.
        When ``None`` the previously loaded settings are reused.
    """
    if settings is None:
        # Re‑use the default settings that were created at import time.
        settings = _default_settings
    _configure_logger(settings)


def set_level(level: str) -> None:
    """
    Change the minimum log level at runtime.

    Parameters
    ----------
    level: str
        New log level (e.g. "DEBUG").
    """
    validated = LoggerSettings(level=level)
    _loguru_logger.remove()
    _configure_logger(validated)


def add_sink(
    sink: Union[str, Callable[[str], Any]],
    *,
    level: str = "INFO",
    format: Optional[str] = None,
) -> None:
    """
    Add an additional sink to the logger.

    Parameters
    ----------
    sink: Union[str, Callable[[str], Any]]
        Destination for log output; can be a file path or a callable.
    level: str, default "INFO"
        Minimum severity for this sink.
    format: Optional[str]
        Custom format for this sink; falls back to the global format when omitted.
    """
    validated_level = LoggerSettings(level=level).level
    fmt = format if format is not None else _default_settings.format
    _loguru_logger.add(sink, level=validated_level, format=fmt, enqueue=True)


def bind(**context: Any) -> None:
    """
    Bind additional contextual information to all subsequent log records.

    The bound values are attached to the logger's ``extra`` dictionary and are
    automatically included in the output according to the configured format.
    """
    _loguru_logger = _loguru_logger.bind(**context)  # type: ignore[assignment]


def unbind(*keys: str) -> None:
    """
    Remove previously bound contextual keys.

    Parameters
    ----------
    keys: str
        One or more keys that were added via :func:`bind`.
    """
    _loguru_logger = _loguru_logger.unbind(*keys)  # type: ignore[assignment]


__all__ = [
    "logger",
    "async_logger",
    "LoggerSettings",
    "reload_logger",
    "set_level",
    "add_sink",
    "bind",
    "unbind",
]