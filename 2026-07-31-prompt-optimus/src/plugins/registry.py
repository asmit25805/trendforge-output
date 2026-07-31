import abc
import threading
from collections.abc import Mapping
from typing import Any, Callable, Dict

from src.core.models import ConfigurationError

__all__ = ["BaseLLMDriver", "PluginRegistry"]


class BaseLLMDriver(abc.ABC):
    """Abstract base class for all LLM driver implementations.

    Concrete subclasses must provide a unique ``name`` identifier and a
    ``generate_prompt`` method that returns a :class:`~src.core.models.PromptCandidate`.
    """

    @abc.abstractmethod
    def name(self) -> str:
        """Return the driver name used for registration and lookup."""
        raise NotImplementedError

    @abc.abstractmethod
    def generate_prompt(self, trial_index: int) -> "PromptCandidate":
        """Generate a prompt candidate for the given trial index.

        Parameters
        ----------
        trial_index: int
            Zero‑based index of the current optimisation trial.
        """
        raise NotImplementedError


class PluginRegistry:
    """Thread‑safe singleton that holds registered LLM drivers.

    Drivers are registered via :meth:`register_driver` and retrieved with
    :meth:`get_driver`. The registry raises :class:`ConfigurationError` when a
    requested driver is not available.
    """

    _instance: "PluginRegistry" | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._drivers: Dict[str, BaseLLMDriver] = {}

    @classmethod
    def get_instance(cls) -> "PluginRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register_driver(self, driver: BaseLLMDriver) -> None:
        if driver.name() in self._drivers:
            raise ConfigurationError(f"Driver '{driver.name()}' is already registered.")
        self._drivers[driver.name()] = driver

    def get_driver(self, name: str) -> BaseLLMDriver:
        try:
            return self._drivers[name]
        except KeyError as exc:
            raise ConfigurationError(f"Driver '{name}' not found. Available drivers: {list(self._drivers)}") from exc
