import pytest
from typing import Any, Mapping

from src.plugins.registry import BaseLLMDriver, PluginRegistry, ConfigurationError


class DummyDriver(BaseLLMDriver):
    """Simple driver that echoes a key from the context."""

    def __init__(self) -> None:
        self._last_context: Mapping[str, Any] | None = None

    def name(self) -> str:
        return "dummy"

    def generate_prompt(self, trial_index: int) -> "PromptCandidate":
        # Store the index for later inspection and return a deterministic candidate
        self._last_context = {"trial_index": trial_index}
        from src.core.models import PromptCandidate
        return PromptCandidate(prompt=f"dummy prompt {trial_index}")


def test_register_and_retrieve_driver():
    registry = PluginRegistry.get_instance()
    # Ensure a clean registry for the test
    registry._drivers.clear()
    driver = DummyDriver()
    registry.register_driver(driver)
    retrieved = registry.get_driver("dummy")
    assert retrieved is driver


def test_duplicate_registration_raises():
    registry = PluginRegistry.get_instance()
    registry._drivers.clear()
    driver = DummyDriver()
    registry.register_driver(driver)
    with pytest.raises(ConfigurationError):
        registry.register_driver(driver)


def test_unknown_driver_raises():
    registry = PluginRegistry.get_instance()
    registry._drivers.clear()
    with pytest.raises(ConfigurationError):
        registry.get_driver("nonexistent")
